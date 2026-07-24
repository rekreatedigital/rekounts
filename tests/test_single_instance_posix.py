"""POSIX single-instance lockfile (macOS/Linux; the Windows path is the mutex).

fcntl does not exist on Windows, so these run only on the posix CI legs —
which is the point: macos-latest exercises the exact code the mac app runs.
"""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="fcntl lockfile is the posix path")


def test_first_acquire_wins_and_creates_the_file(tmp_path):
    from rekounts.__main__ import _acquire_posix_lock

    lock = _acquire_posix_lock(tmp_path / "app" / ".rekounts.lock")
    assert lock is not None
    assert (tmp_path / "app" / ".rekounts.lock").exists()
    lock.close()


def test_second_acquire_is_refused_while_held(tmp_path):
    from rekounts.__main__ import _acquire_posix_lock

    path = tmp_path / ".rekounts.lock"
    first = _acquire_posix_lock(path)
    assert first is not None
    assert _acquire_posix_lock(path) is None      # someone is already running
    first.close()


def test_release_frees_the_next_instance(tmp_path):
    """The kernel drops the flock with the fd — a crash can never leave a
    stale lock that blocks every later launch."""
    from rekounts.__main__ import _acquire_posix_lock

    path = tmp_path / ".rekounts.lock"
    first = _acquire_posix_lock(path)
    first.close()
    second = _acquire_posix_lock(path)
    assert second is not None
    second.close()


def test_acquire_single_instance_routes_to_the_lockfile(monkeypatch, tmp_path):
    import rekounts.__main__ as main_mod

    monkeypatch.setenv("APPDATA", str(tmp_path))   # pins app_data_dir
    claim = main_mod._acquire_single_instance()
    assert claim is not None
    assert (tmp_path / "Rekounts" / ".rekounts.lock").exists()
    assert main_mod._acquire_single_instance() is None   # second instance
    claim.close()
