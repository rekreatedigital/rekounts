import threading
from datetime import datetime, timedelta, timezone

import pytest

from rekounts.history import History


@pytest.fixture
def store(tmp_path):
    h = History(path=tmp_path / "history.db")
    yield h
    h.close()


def _days_ago(n, hour=12):
    """A UTC datetime n local-days ago (noon keeps it clear of tz edges)."""
    return datetime.now(timezone.utc).astimezone().replace(
        hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=n)


# --------------------------------------------------------------- basic CRUD
def test_add_and_page_newest_first(store):
    store.add("raw one", "One two three", 2.0, inserted=True)
    store.add("raw two", "Four five", 1.0, inserted=False)
    rows = store.page(0, 10)
    assert len(rows) == 2
    assert rows[0]["cleaned_text"] == "Four five"   # newest first
    assert rows[0]["inserted"] == 0
    assert rows[1]["word_count"] == 3


def test_add_returns_id_and_counts_words_from_cleaned(store):
    rid = store.add("um four words here roughly", "four words here", 1.0)
    assert isinstance(rid, int)
    assert store.page(0, 1)[0]["word_count"] == 3


def test_word_count_falls_back_to_raw_when_cleaned_empty(store):
    store.add("one two three", "", 1.0)
    assert store.page(0, 1)[0]["word_count"] == 3


def test_disabled_add_is_noop(tmp_path):
    h = History(path=tmp_path / "h.db", enabled=False)
    assert h.add("raw", "cleaned text", 1.0) is None
    assert h.count() == 0
    h.enabled = True
    assert h.add("raw", "cleaned text", 1.0) is not None
    assert h.count() == 1
    h.close()


def test_delete_and_clear_all(store):
    a = store.add("a", "alpha", 1.0)
    store.add("b", "bravo", 1.0)
    store.delete(a)
    assert store.count() == 1
    store.clear_all()
    assert store.count() == 0


# ------------------------------------------------------------------ paging
def test_pagination_offset_limit(store):
    for i in range(10):
        store.add(f"r{i}", f"word{i}", 1.0, when=_days_ago(0, hour=i))
    first = store.page(0, 4)
    second = store.page(4, 4)
    assert len(first) == 4 and len(second) == 4
    ids = [r["id"] for r in first] + [r["id"] for r in second]
    assert len(set(ids)) == 8   # no overlap across pages


# ------------------------------------------------------------------ search
def test_search_matches_raw_and_cleaned_case_insensitive(store):
    store.add("meeting notes", "Discuss the Roadmap", 1.0)
    store.add("grocery", "buy milk", 1.0)
    assert len(store.search("roadmap")) == 1
    assert len(store.search("MILK")) == 1
    assert len(store.search("")) == 2   # empty query returns recent page


# -------------------------------------------------------------- stats math
def test_stats_word_windows(store):
    store.add("r", "one two three", 1.0, when=_days_ago(0))     # today: 3
    store.add("r", "four five", 1.0, when=_days_ago(1))         # yesterday: 2
    store.add("r", "old words here now", 1.0, when=_days_ago(30))  # 4, all-time only
    s = store.stats()
    assert s["words_today"] == 3
    assert s["words_7d"] == 5          # today + yesterday within 7-day window
    assert s["words_all"] == 9


def test_avg_wpm(store):
    # 60 words over 60s = 60 wpm; add another 60 words over 60s -> still 60.
    store.add("r", " ".join(["w"] * 60), 60.0, when=_days_ago(0))
    store.add("r", " ".join(["w"] * 30), 30.0, when=_days_ago(1))
    s = store.stats()
    assert s["avg_wpm"] == pytest.approx(60.0)


def test_avg_wpm_zero_when_no_duration(store):
    store.add("r", "some words", 0.0)
    assert store.stats()["avg_wpm"] == 0.0


# ---------------------------------------------------------------- streaks
def test_current_streak_counts_from_today(store):
    for d in (0, 1, 2):
        store.add("r", "word", 1.0, when=_days_ago(d))
    s = store.stats()
    assert s["current_streak"] == 3
    assert s["longest_streak"] == 3


def test_current_streak_alive_from_yesterday(store):
    # No entry today, but a run ending yesterday should still count as current.
    for d in (1, 2, 3):
        store.add("r", "word", 1.0, when=_days_ago(d))
    assert store.stats()["current_streak"] == 3


def test_current_streak_broken_when_gap(store):
    store.add("r", "word", 1.0, when=_days_ago(0))
    store.add("r", "word", 1.0, when=_days_ago(3))   # gap at day 1 & 2
    assert store.stats()["current_streak"] == 1


def test_longest_streak_finds_best_run(store):
    for d in (10, 11, 12, 13):        # a 4-day run in the past
        store.add("r", "word", 1.0, when=_days_ago(d))
    store.add("r", "word", 1.0, when=_days_ago(0))   # isolated today
    s = store.stats()
    assert s["longest_streak"] == 4
    assert s["current_streak"] == 1


def test_multiple_entries_same_day_count_one_streak_day(store):
    store.add("r", "a", 1.0, when=_days_ago(0, hour=9))
    store.add("r", "b", 1.0, when=_days_ago(0, hour=17))
    assert store.stats()["current_streak"] == 1
    assert store.stats()["active_days"] == 1


def test_empty_stats(store):
    s = store.stats()
    assert s["current_streak"] == 0 and s["longest_streak"] == 0
    assert s["words_all"] == 0 and s["avg_wpm"] == 0.0


# ----------------------------------------------------------- daily_words chart
def test_daily_words_returns_padded_window(store):
    store.add("r", "one two", 1.0, when=_days_ago(0))
    store.add("r", "three", 1.0, when=_days_ago(2))
    series = store.daily_words(days=5)
    assert len(series) == 5
    assert series[-1][1] == 2    # today
    assert series[-3][1] == 1    # two days ago
    assert series[-2][1] == 0    # yesterday, no entries


# ---------------------------------------------------------------- dictionary
def test_dictionary_add_list_delete(store):
    wid = store.add_dictionary_word("Kubernetes", "koober-net-ees")
    store.add_dictionary_word("apple")
    words = store.dictionary_words()
    assert [w["word"] for w in words] == ["apple", "Kubernetes"]  # NOCASE sort
    assert next(w for w in words if w["id"] == wid)["sounds_like"] == "koober-net-ees"
    store.delete_dictionary_word(wid)
    assert len(store.dictionary_words()) == 1


def test_dictionary_ignores_blank(store):
    assert store.add_dictionary_word("   ") is None
    assert store.dictionary_words() == []


# ------------------------------------------- dictionary -> recognition providers
def test_dictionary_hotwords_returns_just_the_words(store):
    store.add_dictionary_word("Kubernetes", "koober-net-ees")
    store.add_dictionary_word("apple")
    assert store.dictionary_hotwords() == ["apple", "Kubernetes"]


def test_dictionary_hotwords_is_empty_when_nothing_is_stored(store):
    assert store.dictionary_hotwords() == []


def test_dictionary_replacements_skips_entries_without_a_sounds_like(store):
    store.add_dictionary_word("Kubernetes", "koober net ees")
    store.add_dictionary_word("apple")                 # no sounds_like
    store.add_dictionary_word("Grafana", "   ")        # whitespace only
    assert store.dictionary_replacements() == [("koober net ees", "Kubernetes")]


def test_dictionary_replacements_are_longest_first(store):
    store.add_dictionary_word("Netties", "netties")
    store.add_dictionary_word("Kubernetes", "cooper netties")
    assert store.dictionary_replacements()[0] == ("cooper netties", "Kubernetes")


def test_dictionary_replacements_are_trimmed(store):
    store.add_dictionary_word("  Kubernetes  ", "  koober net ees  ")
    assert store.dictionary_replacements() == [("koober net ees", "Kubernetes")]


def test_deleting_a_word_removes_it_from_both_providers(store):
    wid = store.add_dictionary_word("Kubernetes", "koober net ees")
    store.delete_dictionary_word(wid)
    assert store.dictionary_hotwords() == []
    assert store.dictionary_replacements() == []


# --------------------------------------------------------------- thread safety
def test_concurrent_writes_are_safe(store):
    def worker(base):
        for i in range(50):
            store.add(f"raw {base}-{i}", f"word{base} {i}", 1.0)

    threads = [threading.Thread(target=worker, args=(b,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.count() == 8 * 50


def test_concurrent_read_write_no_error(store):
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            store.add("r", f"word {i}", 1.0)
            i += 1

    def reader():
        while not stop.is_set():
            store.page(0, 20)
            store.stats()

    w = threading.Thread(target=writer)
    r = threading.Thread(target=reader)
    w.start(); r.start()
    threading.Event().wait(0.2)
    stop.set()
    w.join(); r.join()
    assert store.count() > 0
