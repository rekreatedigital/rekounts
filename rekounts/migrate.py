"""One-time migration of user state from the old app name to the new one.

The app was renamed TalkativeAI -> Rekounts. Everything the user cares about —
settings, dictation history, the custom dictionary, downloaded speech models,
launch-at-login — lived under the old name. An upgrading user must keep all of
it with ZERO manual steps, so this module moves it across on first launch.

Design, and why:

* **Marker, not "target is missing".** "Migrate if %APPDATA%\\Rekounts does not
  exist" looks obvious and is wrong: logging creates that folder before anything
  else runs, so the check would be false on the very first launch and the
  migration would silently never happen. Completion is recorded explicitly, by
  :data:`MARKER_NAME`, and that marker is the only thing that stops a retry.

* **Per item, skip what is already there.** Each entry is migrated
  independently and never overwrites an entry that already exists at the target.
  A run that dies halfway leaves the marker unwritten, so the next launch simply
  finishes the remainder. That makes the operation idempotent and makes
  "partially migrated" a recoverable state rather than a corrupt one.

* **Copy the small state, move the models.** Copies are cheap and reversible:
  the old install still works if the user rolls back, because its data is still
  there. Models are the exception — they are hundreds of megabytes to gigabytes,
  a copy could need more free disk than the user has, and within one %APPDATA%
  the move is an instant same-volume rename. The cost is that a rollback
  re-downloads the model, which is recoverable; running out of disk mid-upgrade
  is not.

* **Atomic per item.** Each item lands at a temporary name inside the target
  folder and is then renamed into place, so a crash or a full disk can never
  leave a half-written config.json where a whole one is expected.

* **Moved items are never stranded in staging.** The models move is two renames
  (into ``.migrating-models``, then into place), and after the first one the
  staging name holds the ONLY copy — the legacy folder no longer has it. So a
  crash between the renames must not feed that debris to the sweeper: when move
  debris has no final target (and no legacy source to re-stage from), the next
  run renames it into place instead of deleting it. A completed rename is
  atomic, so such debris is always whole, never truncated.

* **The old folder is never deleted.** A migration that also destroys the only
  copy of the data has no undo. Users are told in the release notes that
  %APPDATA%\\TalkativeAI can be deleted once they are happy.

This module deliberately does no logging of its own. It has to run BEFORE
logging is configured (the log folder is one of the things being migrated), so
it reports everything through its return value and lets the caller log once the
handlers exist.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from rekounts.paths import app_data_dir, legacy_app_data_dir

# Written into the new data folder once every item has come across. Its presence
# is what makes this a one-time operation.
MARKER_NAME = ".migrated-from-talkativeai"

# Migrated by MOVE rather than by copy — see the module docstring.
MOVE_ITEMS = frozenset({"models"})

# Temporary names use this prefix so a crashed run's debris is recognisable and
# is cleaned up by the next run instead of accumulating.
_TMP_PREFIX = ".migrating-"


@dataclass
class MigrationResult:
    """What a migration attempt actually did — for logging and for tests."""

    attempted: bool = False
    copied: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # already at the target
    failed: list[tuple[str, str]] = field(default_factory=list)  # (item, error)
    complete: bool = False   # marker written; no retry on the next launch

    @property
    def migrated(self) -> list[str]:
        return sorted(self.copied + self.moved)

    def summary(self) -> str:
        return (f"migrated={self.migrated} skipped={self.skipped} "
                f"failed={[n for n, _ in self.failed]} complete={self.complete}")


def needs_migration(new_dir: Path, legacy_dir: Path) -> bool:
    """True when there is old-name data to bring across and we have not finished.

    Deliberately does NOT consider whether the new folder already holds data:
    per-item skipping protects anything already there, and treating a populated
    target as "nothing to do" is exactly what would strand history.db after a
    run that copied config.json and then died.
    """
    if legacy_dir == new_dir:
        return False   # non-Windows fallback could resolve both to one place
    if not legacy_dir.is_dir():
        return False
    return not (new_dir / MARKER_NAME).exists()


def _clear_debris(new_dir: Path,
                  legacy_dir: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Handle leftovers from a run that died mid-item.

    Copied items' debris is simply deleted: their source still exists under the
    old name, so the item is re-staged whole by the normal pass. Debris of a
    MOVED item is the opposite case — its source was renamed away the moment
    staging finished, so the debris can be the ONLY copy of the user's data (a
    crash between the move's two renames does exactly this). Deleting it would
    complete the data loss and the marker would then record the migration as
    done, so when a move item's debris has no final target — and no legacy
    source to re-stage from, proving the debris is the authoritative copy — it
    is RESCUED into place instead. A completed rename is atomic, so that debris
    is always whole.

    Returns ``(rescued_names, failures)``. Failures must reach the caller's
    ``result.failed``: a rescue that did not happen has to block the completion
    marker, or the debris would be orphaned forever behind a "done" record.
    """
    rescued: list[str] = []
    failures: list[tuple[str, str]] = []
    try:
        entries = list(new_dir.iterdir())
    except OSError:
        return rescued, failures
    for entry in entries:
        if not entry.name.startswith(_TMP_PREFIX):
            continue
        name = entry.name[len(_TMP_PREFIX):]
        target = new_dir / name
        if (name in MOVE_ITEMS and not target.exists()
                and not (legacy_dir / name).exists()):
            try:
                os.replace(entry, target)
                rescued.append(name)
            except OSError as e:
                # NEVER fall through to deletion here — this debris is the only
                # copy. Leave it in place; the recorded failure withholds the
                # marker, so the next launch retries this rescue.
                failures.append((name, "could not finish the interrupted "
                                       "move: %s" % e))
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink()
        except OSError:
            pass
    return rescued, failures


def _stage_then_place(source: Path, target: Path, move: bool) -> None:
    """Put ``source`` at ``target`` atomically, via a temporary in the same dir.

    Same-directory staging keeps the final step a rename rather than a copy, so
    the item is either entirely absent or entirely present — never truncated.
    """
    tmp = target.with_name(_TMP_PREFIX + target.name)
    if tmp.exists():
        if tmp.is_dir():
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            tmp.unlink()

    if move:
        # shutil.move handles the cross-volume case by falling back to a copy;
        # inside one %APPDATA% it is a plain rename.
        shutil.move(str(source), str(tmp))
    elif source.is_dir():
        shutil.copytree(source, tmp)
    else:
        shutil.copy2(source, tmp)

    try:
        os.replace(tmp, target)
    except OSError:
        # os.replace refuses to replace a non-empty directory on Windows. The
        # caller only ever stages items whose target is absent, so target
        # present means we raced another instance; leave the winner's data
        # alone and drop ours. But a MOVED item with nothing at the target is
        # different: its source is already gone (staging renamed it away), so
        # the tmp is the ONLY copy left — deleting it here would BE the data
        # loss. Keep it as recognisable debris and let the next run's
        # _clear_debris rename it into place.
        if move and not target.exists():
            raise
        if tmp.is_dir():
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            tmp.unlink(missing_ok=True)
        raise


def migrate_app_data(new_dir: Path | None = None,
                     legacy_dir: Path | None = None) -> MigrationResult:
    """Bring TalkativeAI's user data across to Rekounts. Safe to call always.

    Returns a :class:`MigrationResult` describing what happened; never raises
    for an ordinary filesystem failure, because a failed migration must not stop
    the app from starting — it degrades to "some data did not come across yet"
    and retries on the next launch.
    """
    new_dir = Path(new_dir) if new_dir is not None else app_data_dir()
    legacy_dir = (Path(legacy_dir) if legacy_dir is not None
                  else legacy_app_data_dir())

    result = MigrationResult()
    if not needs_migration(new_dir, legacy_dir):
        return result
    result.attempted = True

    try:
        new_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        result.failed.append(("<target directory>", str(e)))
        return result

    # The sweep can also *finish* an interrupted models move (see
    # _clear_debris): a rescue counts as the move happening, and a failed
    # rescue must block the completion marker exactly like a failed item.
    rescued, rescue_failures = _clear_debris(new_dir, legacy_dir)
    result.moved.extend(rescued)
    result.failed.extend(rescue_failures)

    try:
        entries = sorted(legacy_dir.iterdir(), key=lambda p: p.name)
    except OSError as e:
        result.failed.append(("<source directory>", str(e)))
        return result

    for source in entries:
        name = source.name
        if name.startswith(_TMP_PREFIX):
            continue   # the old folder's own debris; not user data
        target = new_dir / name
        if target.exists():
            result.skipped.append(name)
            continue
        move = name in MOVE_ITEMS
        try:
            _stage_then_place(source, target, move=move)
        except (OSError, shutil.Error) as e:
            result.failed.append((name, str(e)))
            continue
        (result.moved if move else result.copied).append(name)

    if not result.failed:
        try:
            (new_dir / MARKER_NAME).write_text(
                "User data was migrated here from %APPDATA%\\TalkativeAI.\n"
                "Delete that folder once you are happy with this version.\n",
                encoding="utf-8")
            result.complete = True
        except OSError as e:
            # Everything is across; only the "don't do it again" record failed.
            # The next launch re-runs and skips every item, which is harmless.
            result.failed.append((MARKER_NAME, str(e)))

    return result
