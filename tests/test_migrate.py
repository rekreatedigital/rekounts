"""Tests for the TalkativeAI -> Rekounts user-state migration.

Every test drives temp directories and a fake registry. Nothing here may touch
the real %APPDATA% or the real HKCU — the migration is the one piece of this
rename that can destroy a user's history if it is wrong, so its tests must never
be able to destroy the developer's.
"""
import os
import shutil

import pytest

from rekounts import startup
from rekounts.migrate import (MARKER_NAME, MigrationResult, migrate_app_data,
                              needs_migration)
from tests.test_startup import FakeWinreg, _approval_value, _set_approval


@pytest.fixture
def dirs(tmp_path):
    """A (legacy, new) pair of data folders, neither created yet."""
    return tmp_path / "TalkativeAI", tmp_path / "Rekounts"


def populate_legacy(legacy):
    """A realistic old-name data folder: config, history, logs, a backup, models."""
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "config.json").write_text('{"hotkey": "ctrl+win"}', encoding="utf-8")
    (legacy / "config.json.bak").write_text("{broken", encoding="utf-8")
    (legacy / "history.db").write_bytes(b"SQLite format 3\x00fake")
    (legacy / "logs").mkdir()
    (legacy / "logs" / "talkativeai.log").write_text("old log", encoding="utf-8")
    (legacy / "models").mkdir()
    (legacy / "models" / "small").mkdir()
    (legacy / "models" / "small" / "model.bin").write_bytes(b"x" * 64)
    return legacy


# --- the three scenarios that matter ----------------------------------------

def test_fresh_install_does_nothing(dirs):
    """No old folder: no migration, no marker, no directories invented."""
    legacy, new = dirs
    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.attempted is False
    assert result.migrated == []
    assert result.complete is False
    assert not new.exists()


def test_upgrade_brings_everything_across(dirs):
    """The whole point: settings, history, dictionary, logs and models survive."""
    legacy, new = dirs
    populate_legacy(legacy)

    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.attempted is True
    assert result.complete is True
    assert result.failed == []
    assert (new / "config.json").read_text(encoding="utf-8") == '{"hotkey": "ctrl+win"}'
    assert (new / "config.json.bak").read_text(encoding="utf-8") == "{broken"
    assert (new / "history.db").read_bytes() == b"SQLite format 3\x00fake"
    assert (new / "logs" / "talkativeai.log").read_text(encoding="utf-8") == "old log"
    assert (new / "models" / "small" / "model.bin").read_bytes() == b"x" * 64


def test_partial_migration_is_completed_not_abandoned(dirs):
    """A run that died after config.json must still rescue history.db.

    This is the case a "migrate only if the target folder is missing" check gets
    wrong: the target exists and looks plausible, so history would be stranded
    under the old name forever.
    """
    legacy, new = dirs
    populate_legacy(legacy)
    new.mkdir(parents=True)
    (new / "config.json").write_text('{"hotkey": "ctrl+win"}', encoding="utf-8")

    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.complete is True
    assert "config.json" in result.skipped        # already there, left alone
    assert "history.db" in result.migrated        # the rescue
    assert (new / "history.db").read_bytes() == b"SQLite format 3\x00fake"


# --- idempotency and non-destruction ----------------------------------------

def test_second_launch_is_a_no_op(dirs):
    """The marker makes this one-time; a re-run must not re-copy or re-fail."""
    legacy, new = dirs
    populate_legacy(legacy)
    migrate_app_data(new_dir=new, legacy_dir=legacy)

    again = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert again.attempted is False
    assert again.migrated == []


def test_existing_data_is_never_overwritten(dirs):
    """New-name data always wins; migration only fills genuine gaps."""
    legacy, new = dirs
    populate_legacy(legacy)
    new.mkdir(parents=True)
    (new / "config.json").write_text('{"hotkey": "f9"}', encoding="utf-8")

    migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert (new / "config.json").read_text(encoding="utf-8") == '{"hotkey": "f9"}'


def test_old_folder_survives_except_models(dirs):
    """Copies leave a rollback path; only the large models folder is moved."""
    legacy, new = dirs
    populate_legacy(legacy)

    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert (legacy / "config.json").exists()
    assert (legacy / "history.db").exists()
    assert (legacy / "logs" / "talkativeai.log").exists()
    assert not (legacy / "models").exists()       # moved, not copied
    assert result.moved == ["models"]
    assert "models" not in result.copied


def test_marker_records_completion(dirs):
    legacy, new = dirs
    populate_legacy(legacy)

    migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert (new / MARKER_NAME).exists()
    assert needs_migration(new, legacy) is False


# --- failure handling --------------------------------------------------------

def test_one_bad_item_does_not_block_the_others(dirs, monkeypatch):
    """History must still arrive when, say, a locked log file cannot be copied."""
    legacy, new = dirs
    populate_legacy(legacy)

    import rekounts.migrate as migrate_mod
    real = migrate_mod.shutil.copytree

    def explode(src, dst, *a, **kw):
        if os.path.basename(str(src)) == "logs":
            raise OSError(13, "in use by another process")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(migrate_mod.shutil, "copytree", explode)
    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert [n for n, _ in result.failed] == ["logs"]
    assert (new / "history.db").exists()
    assert (new / "config.json").exists()
    # No marker: the failure is retried next launch rather than declared done.
    assert result.complete is False
    assert not (new / MARKER_NAME).exists()
    assert needs_migration(new, legacy) is True


def test_retry_after_a_failure_finishes_the_job(dirs, monkeypatch):
    legacy, new = dirs
    populate_legacy(legacy)

    import rekounts.migrate as migrate_mod
    real = migrate_mod.shutil.copytree
    monkeypatch.setattr(migrate_mod.shutil, "copytree",
                        lambda src, dst, *a, **kw: (_ for _ in ()).throw(
                            OSError("locked")) if os.path.basename(str(src)) == "logs"
                        else real(src, dst, *a, **kw))
    migrate_app_data(new_dir=new, legacy_dir=legacy)
    monkeypatch.setattr(migrate_mod.shutil, "copytree", real)

    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.complete is True
    assert (new / "logs" / "talkativeai.log").read_text(encoding="utf-8") == "old log"


def test_crash_debris_is_cleaned_and_never_mistaken_for_data(dirs):
    """A half-written temp file from a killed run must not become real data."""
    legacy, new = dirs
    populate_legacy(legacy)
    new.mkdir(parents=True)
    (new / ".migrating-history.db").write_bytes(b"truncat")

    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.complete is True
    assert (new / "history.db").read_bytes() == b"SQLite format 3\x00fake"
    assert not (new / ".migrating-history.db").exists()


def test_models_move_debris_is_rescued_not_deleted(dirs):
    """The reproduced data loss: models are MOVED via two renames, and a crash
    between them leaves them ONLY as .migrating-models — the legacy copy is
    already gone. The old debris sweep deleted that folder and the run then
    wrote the marker, losing the models on both sides. The sweep must instead
    finish the move: debris into place, marker written, nothing re-downloaded.
    """
    legacy, new = dirs
    populate_legacy(legacy)
    new.mkdir(parents=True)
    # The crash: rename #1 completed (legacy models gone, debris whole under
    # the new dir), rename #2 never ran (no final models folder).
    shutil.move(str(legacy / "models"), str(new / ".migrating-models"))
    assert not (legacy / "models").exists()

    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert (new / "models" / "small" / "model.bin").read_bytes() == b"x" * 64
    assert not (new / ".migrating-models").exists()
    assert "models" in result.moved          # the rescue is the move, completed
    assert result.complete is True
    assert (new / MARKER_NAME).exists()


def test_failed_models_placement_keeps_the_only_copy_for_the_next_launch(
        dirs, monkeypatch):
    """When the final rename fails, the staged models are the ONLY copy (the
    source was renamed away by staging). The copy-item cleanup — delete the
    tmp — would BE the data loss here, so the debris must survive, the failure
    must block the marker, and the next launch's sweep completes the move."""
    legacy, new = dirs
    populate_legacy(legacy)

    import rekounts.migrate as migrate_mod
    real_replace = migrate_mod.os.replace

    def deny_models(src, dst, *args, **kwargs):
        if os.path.basename(str(dst)) == "models":
            raise OSError(5, "access denied")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(migrate_mod.os, "replace", deny_models)
    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert "models" in [n for n, _ in result.failed]
    assert result.complete is False          # marker withheld -> retry happens
    assert not (legacy / "models").exists()  # source is gone, so...
    assert (new / ".migrating-models" / "small"
            / "model.bin").read_bytes() == b"x" * 64   # ...debris must live on

    monkeypatch.setattr(migrate_mod.os, "replace", real_replace)
    retry = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert (new / "models" / "small" / "model.bin").read_bytes() == b"x" * 64
    assert not (new / ".migrating-models").exists()
    assert "models" in retry.moved
    assert retry.complete is True


def test_a_failed_rescue_blocks_the_marker_instead_of_orphaning_the_debris(
        dirs, monkeypatch):
    """If the rescue itself fails (transient lock), completing the migration
    anyway would strand the models behind a "done" marker forever."""
    legacy, new = dirs
    populate_legacy(legacy)
    new.mkdir(parents=True)
    shutil.move(str(legacy / "models"), str(new / ".migrating-models"))

    import rekounts.migrate as migrate_mod
    real_replace = migrate_mod.os.replace

    def deny_models(src, dst, *args, **kwargs):
        if os.path.basename(str(dst)) == "models":
            raise OSError(5, "access denied")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(migrate_mod.os, "replace", deny_models)
    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.complete is False
    assert not (new / MARKER_NAME).exists()
    assert (new / ".migrating-models" / "small"
            / "model.bin").read_bytes() == b"x" * 64   # never deleted


def test_unreadable_source_is_survivable(dirs, monkeypatch):
    """A migration that cannot even list the old folder must not raise."""
    legacy, new = dirs
    populate_legacy(legacy)

    import rekounts.migrate as migrate_mod

    def no_iter(self):
        raise OSError(5, "access denied")

    monkeypatch.setattr(migrate_mod.Path, "iterdir", no_iter)
    result = migrate_app_data(new_dir=new, legacy_dir=legacy)

    assert result.complete is False
    assert result.failed and result.failed[0][0] == "<source directory>"


def test_same_source_and_target_is_refused(tmp_path):
    """The portable non-Windows fallback could resolve both names to one path."""
    same = tmp_path / "data"
    same.mkdir()
    assert needs_migration(same, same) is False


def test_result_summary_is_loggable():
    assert "complete=False" in MigrationResult().summary()


# --- the Run key -------------------------------------------------------------

def test_legacy_run_value_is_removed(dirs):
    """A leftover old entry would launch the stale checkout at every login."""
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", r'"C:\old\pythonw.exe" "C:\old\launch.py"')

    assert startup.legacy_is_registered(backend=backend) is True
    assert startup.purge_legacy(backend=backend) is True
    assert backend.current("TalkativeAI") is None
    assert startup.legacy_is_registered(backend=backend) is False


def test_purging_the_legacy_entry_leaves_ours_alone(dirs):
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", r'"C:\old\pythonw.exe" "C:\old\launch.py"')
    backend.enable("Rekounts", r'"C:\new\pythonw.exe" "C:\new\launch.py"')

    startup.purge_legacy(backend=backend)

    assert backend.current("Rekounts") == r'"C:\new\pythonw.exe" "C:\new\launch.py"'
    assert backend.is_enabled("Rekounts") is True


def test_purge_is_idempotent_when_there_was_no_legacy_entry(dirs):
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)

    assert startup.purge_legacy(backend=backend) is False
    assert startup.purge_legacy(backend=backend) is False


def test_purge_also_clears_a_task_manager_disable_flag(dirs):
    """Otherwise an orphaned StartupApproved value outlives the name it describes."""
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", "cmd")
    _set_approval(backend, "TalkativeAI", 0x03)   # "disabled" in Task Manager

    startup.purge_legacy(backend=backend)

    assert _approval_value(backend, "TalkativeAI") is None


def test_legacy_run_value_purge_does_not_touch_other_apps(dirs):
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", "cmd")
    backend.enable("SomeOtherApp", "other-cmd")

    startup.purge_legacy(backend=backend)

    assert backend.current("SomeOtherApp") == "other-cmd"


def test_frozen_and_source_flavours_both_purge(dirs):
    """The old entry is removed whichever way the old app was installed."""
    for command in (r'"C:\Program Files\TalkativeAI\TalkativeAI.exe"',
                    r'"C:\py\pythonw.exe" "C:\repo\launch.py"'):
        fake = FakeWinreg()
        backend = startup.WindowsRegistryBackend(winreg_module=fake)
        backend.enable("TalkativeAI", command)

        assert startup.purge_legacy(backend=backend) is True
        assert backend.current("TalkativeAI") is None


# --- the launch-at-login reconcile on upgrade --------------------------------

class FakeConfig:
    """Just enough of rekounts.config.Config for the startup reconcile."""

    def __init__(self, values):
        self.values = dict(values)
        self.saves = 0

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.saves += 1


def _reconcile(cfg, backend):
    import rekounts.__main__ as main_mod
    main_mod._reconcile_startup(cfg, backend=backend)


def test_a_task_manager_disable_of_the_old_app_is_not_resurrected(dirs):
    """The user's last word was OFF — set in Task Manager, which edits the
    registry, not our config. Upgrading with a stale launch_on_startup:true
    must sync the config off and register NOTHING under the new name, while
    still purging the old entries."""
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", r'"C:\old\pythonw.exe" "C:\old\launch.py"')
    _set_approval(backend, "TalkativeAI", 0x03)     # switched OFF in Task Manager
    cfg = FakeConfig({"launch_on_startup": True})   # stale migrated setting

    _reconcile(cfg, backend)

    assert cfg.values["launch_on_startup"] is False   # config synced to reality
    assert cfg.saves >= 1                             # ...and persisted
    assert backend.current("Rekounts") is None        # nothing registered
    assert backend.current("TalkativeAI") is None     # stale entry still purged
    assert _approval_value(backend, "TalkativeAI") is None   # flag purged too


def test_an_enabled_legacy_entry_still_carries_across_to_the_new_name(dirs):
    """No Task Manager disable -> unchanged behavior: register under the new
    name from the migrated setting, then purge the old entry."""
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", r'"C:\old\pythonw.exe" "C:\old\launch.py"')
    cfg = FakeConfig({"launch_on_startup": True})

    _reconcile(cfg, backend)

    assert cfg.values["launch_on_startup"] is True
    assert backend.current("Rekounts") is not None
    assert backend.is_enabled("Rekounts") is True
    assert backend.current("TalkativeAI") is None


def test_an_explicit_task_manager_enable_flag_also_carries_across(dirs):
    """0x02 (explicitly enabled) must read as enabled, not as disabled."""
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", "old-cmd")
    _set_approval(backend, "TalkativeAI", 0x02)
    cfg = FakeConfig({"launch_on_startup": True})

    _reconcile(cfg, backend)

    assert cfg.values["launch_on_startup"] is True
    assert backend.current("Rekounts") is not None
    assert backend.current("TalkativeAI") is None


def test_config_off_stays_off_and_the_legacy_entry_is_still_purged(dirs):
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("TalkativeAI", "old-cmd")
    _set_approval(backend, "TalkativeAI", 0x03)
    cfg = FakeConfig({"launch_on_startup": False})

    _reconcile(cfg, backend)

    assert cfg.values["launch_on_startup"] is False
    assert backend.current("Rekounts") is None
    assert backend.current("TalkativeAI") is None


def test_our_own_task_manager_disable_still_syncs_config_off(dirs):
    """The pre-existing rule the reconcile always had, pinned now that the
    logic is extracted: registered but disabled in Task Manager -> config OFF,
    command left in place, no silent re-enable."""
    fake = FakeWinreg()
    backend = startup.WindowsRegistryBackend(winreg_module=fake)
    backend.enable("Rekounts", "cmd")
    _set_approval(backend, "Rekounts", 0x03)
    cfg = FakeConfig({"launch_on_startup": True})

    _reconcile(cfg, backend)

    assert cfg.values["launch_on_startup"] is False
    assert backend.current("Rekounts") == "cmd"       # command not deleted
    assert _approval_value(backend, "Rekounts") is not None   # user's flag kept


# --- the single-instance mutex across the rename -----------------------------

class FakeKernel32:
    """The three Win32 calls the instance check uses, recorded for assertions."""

    def __init__(self, existing_mutexes=()):
        self.existing = set(existing_mutexes)
        self.opened = []
        self.created = []
        self.closed = []
        self._next_handle = 100

    def OpenMutexW(self, access, inherit, name):
        self.opened.append(name)
        if name not in self.existing:
            return 0            # Win32 returns NULL when the object is absent
        self._next_handle += 1
        return self._next_handle

    def CreateMutexW(self, attrs, initial_owner, name):
        self.created.append(name)
        self._next_handle += 1
        return self._next_handle

    def GetLastError(self):
        return 0

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


@pytest.fixture
def fake_kernel32(monkeypatch):
    """Install a fake windll.kernel32 — also makes these tests run on posix CI."""
    import ctypes

    def install(kernel):
        monkeypatch.setattr(ctypes, "windll",
                            type("W", (), {"kernel32": kernel})(), raising=False)
        return kernel

    return install


def test_old_instance_is_detected_through_its_own_mutex_name(fake_kernel32):
    """The renamed mutex is blind to the old app; the legacy probe is what sees it."""
    from rekounts.__main__ import _LEGACY_MUTEX_NAME, _legacy_instance_running

    kernel = fake_kernel32(FakeKernel32(existing_mutexes={_LEGACY_MUTEX_NAME}))

    assert _legacy_instance_running() is True
    assert kernel.opened == [_LEGACY_MUTEX_NAME]


def test_no_old_instance_reports_false(fake_kernel32):
    from rekounts.__main__ import _legacy_instance_running

    fake_kernel32(FakeKernel32())

    assert _legacy_instance_running() is False


def test_probe_never_creates_the_legacy_mutex(fake_kernel32):
    """Creating it would make US its owner, blocking the old app the user may
    deliberately go back to, and reporting "running" to every later launch."""
    from rekounts.__main__ import _legacy_instance_running

    kernel = fake_kernel32(FakeKernel32())
    _legacy_instance_running()

    assert kernel.created == []


def test_probe_releases_the_handle_it_opened(fake_kernel32):
    from rekounts.__main__ import _LEGACY_MUTEX_NAME, _legacy_instance_running

    kernel = fake_kernel32(FakeKernel32(existing_mutexes={_LEGACY_MUTEX_NAME}))
    _legacy_instance_running()

    assert len(kernel.closed) == 1


def test_a_broken_probe_never_blocks_startup(monkeypatch):
    """No Win32 at all (posix, or a locked-down box) must not stop the app."""
    import ctypes

    from rekounts.__main__ import _legacy_instance_running

    class Exploding:
        @property
        def kernel32(self):
            raise OSError("no win32 here")

    monkeypatch.setattr(ctypes, "windll", Exploding(), raising=False)
    assert _legacy_instance_running() is False


def test_the_two_mutex_names_are_distinct():
    """Guards an accidental revert to a shared name (or to no rename at all)."""
    from rekounts.__main__ import _LEGACY_MUTEX_NAME, _MUTEX_NAME

    assert _MUTEX_NAME == "Rekounts_SingleInstance"
    assert _LEGACY_MUTEX_NAME == "TalkativeAI_SingleInstance"


def test_run_stops_before_starting_when_the_old_app_is_live(monkeypatch):
    """Exiting with an explanation beats two apps fighting over the hotkey."""
    import rekounts.__main__ as main_mod

    shown = []
    monkeypatch.setattr(main_mod, "_legacy_instance_running", lambda: True)
    monkeypatch.setattr(main_mod, "_show_legacy_running_dialog",
                        lambda: shown.append(True))

    def must_not_run():
        raise AssertionError("must not reach the single-instance mutex")

    monkeypatch.setattr(main_mod, "_acquire_single_instance", must_not_run)

    assert main_mod._run() is None
    assert shown == [True]


def test_a_live_legacy_instance_stops_main_before_the_migration(monkeypatch):
    """The ordering that keeps the copy clean: a still-running TalkativeAI can
    be mid-write to its history.db, so main() must show the quit-first dialog
    and exit WITHOUT attempting the migration — not migrate first and only
    then (inside _run) notice the old app."""
    import rekounts.__main__ as main_mod

    events = []
    monkeypatch.setattr(main_mod, "_legacy_instance_running", lambda: True)
    monkeypatch.setattr(main_mod, "_show_legacy_running_dialog",
                        lambda: events.append("dialog"))
    monkeypatch.setattr(main_mod, "_migrate_legacy_state",
                        lambda: events.append("migrate"))
    monkeypatch.setattr(main_mod, "_run", lambda: events.append("run"))

    assert main_mod.main() is None
    assert events == ["dialog"]          # no migration, no app start


def test_the_probe_precedes_the_migration_even_when_the_coast_is_clear(monkeypatch):
    """Pin probe -> migrate -> run so a refactor cannot quietly swap them back."""
    import rekounts.__main__ as main_mod

    events = []
    monkeypatch.setattr(main_mod, "_legacy_instance_running",
                        lambda: (events.append("probe"), False)[1])
    monkeypatch.setattr(main_mod, "_migrate_legacy_state",
                        lambda: (events.append("migrate"), MigrationResult())[1])
    monkeypatch.setattr(main_mod, "setup_logging", lambda: True)
    monkeypatch.setattr(main_mod, "_run", lambda: events.append("run"))

    main_mod.main()

    assert events == ["probe", "migrate", "run"]
