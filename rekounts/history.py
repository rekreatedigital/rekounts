"""Local dictation history + dictionary store (stdlib sqlite3 only).

Everything stays on-disk at %APPDATA%/Rekounts/history.db. Timestamps are
stored in UTC (ISO-8601) and converted to the machine's local time only when
grouping by day for stats/streaks/charts, so a user who dictates across a
midnight-UTC boundary still sees sensible "today"/streak numbers.

Thread-safety: writes arrive from the transcription worker thread while the Qt
UI thread reads. A single shared connection (check_same_thread=False) is guarded
by one re-entrant lock; every public method takes the lock, so concurrent
add()/page()/stats() calls are serialized and safe.
"""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rekounts.paths import history_path as _history_path


def default_history_path() -> Path:
    return _history_path()


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_local_date(iso_ts: str):
    """Parse a stored UTC ISO timestamp and return its LOCAL calendar date."""
    dt = datetime.fromisoformat(iso_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


class History:
    """SQLite-backed store for dictation entries and the pronunciation dictionary."""

    def __init__(self, path: Path | None = None, enabled: bool = True):
        self.path = Path(path) if path else default_history_path()
        # Mutable so the app can flip it live when the user toggles the privacy
        # setting without rebuilding the store.
        self.enabled = enabled
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A single connection shared across threads; the lock below serializes use.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT    NOT NULL,   -- UTC ISO-8601
                    raw_text     TEXT,
                    cleaned_text TEXT,
                    duration_s   REAL    DEFAULT 0,
                    word_count   INTEGER DEFAULT 0,
                    inserted     INTEGER DEFAULT 1   -- 1 = pasted somewhere, 0 = saved here only
                );
                CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(timestamp);

                CREATE TABLE IF NOT EXISTS dictionary (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    word        TEXT NOT NULL,
                    sounds_like TEXT DEFAULT '',
                    created_at  TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------ writes
    def add(self, raw: str, cleaned: str, duration_s: float,
            inserted: bool = True, when: datetime | None = None) -> int | None:
        """Record one dictation. Returns the new row id, or None when disabled.

        Matches the AppController.on_result contract:
            on_result(raw, cleaned, duration_s, inserted)
        `when` is a test/seed seam only — production callers omit it and the
        current UTC time is used.
        """
        if not self.enabled:
            return None
        ts = (when or _utc_now())
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        iso = ts.astimezone(timezone.utc).isoformat()
        wc = _word_count(cleaned) or _word_count(raw)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO entries "
                "(timestamp, raw_text, cleaned_text, duration_s, word_count, inserted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iso, raw, cleaned, float(duration_s or 0), wc, 1 if inserted else 0),
            )
            self._conn.commit()
            return cur.lastrowid

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._conn.commit()

    def clear_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries")
            self._conn.commit()

    # ------------------------------------------------------------------- reads
    def page(self, offset: int = 0, limit: int = 50) -> list[dict]:
        """Entries newest-first, as plain dicts (timestamp still UTC ISO)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM entries ORDER BY timestamp DESC, id DESC "
                "LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 200) -> list[dict]:
        """Case-insensitive substring match over raw + cleaned text."""
        q = (query or "").strip()
        if not q:
            return self.page(0, limit)
        like = f"%{q}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM entries "
                "WHERE cleaned_text LIKE ? OR raw_text LIKE ? "
                "ORDER BY timestamp DESC, id DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM entries").fetchone()[0]

    # --------------------------------------------------------- stats & streaks
    def _daily_words(self) -> dict:
        """Map of local-date -> total words, computed from all entries."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT timestamp, word_count FROM entries").fetchall()
        by_day: dict = {}
        for ts, wc in rows:
            d = _to_local_date(ts)
            by_day[d] = by_day.get(d, 0) + (wc or 0)
        return by_day

    def daily_words(self, days: int = 21) -> list[tuple]:
        """(date, words) for the last `days` local days, oldest-first, gaps=0.

        Ready to feed straight into the Insights bar chart.
        """
        by_day = self._daily_words()
        today = datetime.now().date()
        out = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            out.append((d, by_day.get(d, 0)))
        return out

    @staticmethod
    def _streaks(day_set: set, today) -> tuple:
        """(current, longest) run of consecutive days present in day_set.

        The current streak stays "alive" through today: it counts back from
        today if today has an entry, otherwise from yesterday, so a user who
        hasn't dictated *yet* today doesn't see their streak read as 0.
        """
        if not day_set:
            return 0, 0

        # longest run anywhere
        longest = 0
        for d in day_set:
            if (d - timedelta(days=1)) not in day_set:  # start of a run
                length = 1
                nxt = d + timedelta(days=1)
                while nxt in day_set:
                    length += 1
                    nxt += timedelta(days=1)
                longest = max(longest, length)

        # current run ending today or yesterday
        if today in day_set:
            anchor = today
        elif (today - timedelta(days=1)) in day_set:
            anchor = today - timedelta(days=1)
        else:
            return 0, longest
        current = 0
        d = anchor
        while d in day_set:
            current += 1
            d -= timedelta(days=1)
        return current, longest

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT timestamp, word_count, duration_s FROM entries").fetchall()

        today = datetime.now().date()
        week_ago = today - timedelta(days=6)   # inclusive 7-day window
        words_today = words_7d = words_all = 0
        total_words_for_wpm = 0
        total_seconds = 0.0
        day_set = set()
        for ts, wc, dur in rows:
            wc = wc or 0
            d = _to_local_date(ts)
            day_set.add(d)
            words_all += wc
            if d == today:
                words_today += wc
            if d >= week_ago:
                words_7d += wc
            if dur and dur > 0:
                total_words_for_wpm += wc
                total_seconds += dur

        avg_wpm = (total_words_for_wpm / (total_seconds / 60.0)) if total_seconds else 0.0
        current, longest = self._streaks(day_set, today)
        return {
            "words_today": words_today,
            "words_7d": words_7d,
            "words_all": words_all,
            "avg_wpm": round(avg_wpm, 1),
            "current_streak": current,
            "longest_streak": longest,
            "entries_all": len(rows),
            "active_days": len(day_set),
        }

    # --------------------------------------------------------------- dictionary
    def add_dictionary_word(self, word: str, sounds_like: str = "") -> int | None:
        word = (word or "").strip()
        if not word:
            return None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO dictionary (word, sounds_like, created_at) "
                "VALUES (?, ?, ?)",
                (word, (sounds_like or "").strip(), _utc_now().isoformat()),
            )
            self._conn.commit()
            return cur.lastrowid

    def dictionary_words(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM dictionary ORDER BY word COLLATE NOCASE ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def dictionary_hotwords(self) -> list[str]:
        """Just the words, for biasing recognition.

        Bind this method straight to Transcriber.hotwords_provider - it is read
        fresh per dictation, so a word added in the dashboard takes effect on
        the very next one.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT word FROM dictionary WHERE TRIM(word) != '' "
                "ORDER BY word COLLATE NOCASE ASC"
            ).fetchall()
        return [r[0].strip() for r in rows]

    def dictionary_replacements(self) -> list[tuple[str, str]]:
        """(sounds_like, word) for every entry that has a misheard form.

        Bind this method straight to TextCleaner.replacements_provider. Rows
        without a sounds_like are skipped - there is nothing to replace.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT sounds_like, word FROM dictionary "
                "WHERE TRIM(COALESCE(sounds_like, '')) != '' AND TRIM(word) != '' "
                "ORDER BY LENGTH(sounds_like) DESC"
            ).fetchall()
        return [(r[0].strip(), r[1].strip()) for r in rows]

    def delete_dictionary_word(self, word_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM dictionary WHERE id = ?", (word_id,))
            self._conn.commit()

    # -------------------------------------------------------------------- misc
    def close(self):
        with self._lock:
            self._conn.close()
