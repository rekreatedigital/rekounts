"""Seed the history DB with realistic fake dictations so the dashboard has
something to show. Safe to run repeatedly (each run appends a fresh batch).

Usage (from the repo root):
    .venv\\Scripts\\python.exe scripts\\seed_history.py

Writes to a throwaway DB by default so it never touches your real history:
    scripts\\seed_history.py --real     # write to %APPDATA%/Rekounts/history.db
    scripts\\seed_history.py path.db     # write to an explicit path
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rekounts.history import History, default_history_path  # noqa: E402

SAMPLES = [
    ("Send the roadmap draft to the team before standup.", True),
    ("Remember to buy oat milk and coffee filters.", True),
    ("Let's ship the dashboard behind a feature flag first.", True),
    ("Note to self: the streak logic should survive a missed morning.", False),
    ("Refactor the transcriber warm-up so first use isn't slow.", True),
    ("Meeting moved to three thirty, ping the client.", True),
    ("This one I never pasted anywhere, just thinking out loud.", False),
    ("Kubernetes keeps getting transcribed as cooper netties.", False),
    ("Draft reply: thanks, that works for me, see you then.", True),
    ("Idea for later — a weekly insights email, fully local.", False),
    ("Fix the microphone dropdown so it stops picking the wrong device.", True),
    ("Groceries: eggs, spinach, rice, and something for dinner.", True),
]


def seed(history: History, days: int = 18, per_day_max: int = 5):
    now = datetime.now(timezone.utc)
    total = 0
    for d in range(days):
        # Leave a couple of gaps so streaks are interesting, but keep a run
        # of recent days so the "current streak" reads as > 1.
        if d in (4, 9, 10):
            continue
        for _ in range(random.randint(1, per_day_max)):
            text, inserted = random.choice(SAMPLES)
            when = now - timedelta(
                days=d, hours=random.randint(0, 12), minutes=random.randint(0, 59))
            words = len(text.split())
            duration = round(words / random.uniform(1.8, 3.2), 1)  # ~110-190 wpm
            history.add(text, text, duration, inserted=inserted, when=when)
            total += 1
    # a few dictionary entries too
    for word, sounds in [("Kubernetes", "koober-net-ees"),
                         ("Rekounts", ""), ("faster-whisper", "faster whisper")]:
        history.add_dictionary_word(word, sounds)
    return total


def main():
    args = [a for a in sys.argv[1:]]
    if "--real" in args:
        path = default_history_path()
        args.remove("--real")
    elif args:
        path = Path(args[0])
    else:
        path = Path(__file__).resolve().parent / "seed_preview.db"

    history = History(path=path)
    n = seed(history)
    s = history.stats()
    print(f"Seeded {n} entries into {path}")
    print(f"  words today={s['words_today']}  7d={s['words_7d']}  all={s['words_all']}")
    print(f"  avg wpm={s['avg_wpm']}  current streak={s['current_streak']}  "
          f"longest={s['longest_streak']}")
    history.close()


if __name__ == "__main__":
    main()
