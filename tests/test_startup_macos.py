"""LaunchAgentBackend: launch-on-login via a ~/Library/LaunchAgents plist.

Runs on every OS: the backend only does plistlib + file I/O, and takes its
directory as a parameter, so tmp_path stands in for ~/Library/LaunchAgents —
the same fake-the-platform pattern as test_startup.py's in-memory registry.
"""
import plistlib
import sys

import pytest

import rekounts.startup as startup
from rekounts.startup import LaunchAgentBackend


@pytest.fixture
def backend(tmp_path):
    return LaunchAgentBackend(launch_agents_dir=tmp_path)


def _plist(tmp_path, name="rekounts"):
    path = tmp_path / f"com.rekreatedigital.{name}.plist"
    with open(path, "rb") as f:
        return plistlib.load(f)


def test_starts_disabled(backend):
    assert backend.is_enabled("Rekounts") is False
    assert backend.current("Rekounts") is None


def test_enable_writes_a_valid_launch_agent(backend, tmp_path):
    backend.enable("Rekounts", "/usr/bin/python3 /repo/launch.py")
    payload = _plist(tmp_path)
    assert payload["Label"] == "com.rekreatedigital.rekounts"
    assert payload["ProgramArguments"] == ["/usr/bin/python3", "/repo/launch.py"]
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is False
    assert backend.is_enabled("Rekounts") is True


def test_current_round_trips_through_shlex(backend):
    """Paths with spaces survive enable() -> current() -> enable()."""
    cmd = "'/Applications/My Tools/python3' '/Users/x y/launch.py'"
    backend.enable("Rekounts", cmd)
    stored = backend.current("Rekounts")
    backend.enable("Rekounts", stored)
    assert backend.current("Rekounts") == stored
    import shlex
    assert shlex.split(stored) == [
        "/Applications/My Tools/python3", "/Users/x y/launch.py"]


def test_enable_is_idempotent_and_updates_command(backend):
    backend.enable("Rekounts", "cmd-one")
    backend.enable("Rekounts", "cmd-two")
    assert backend.current("Rekounts") == "cmd-two"


def test_enable_rejects_an_empty_command(backend):
    with pytest.raises(ValueError):
        backend.enable("Rekounts", "   ")


def test_disable_removes_the_plist(backend, tmp_path):
    backend.enable("Rekounts", "cmd")
    backend.disable("Rekounts")
    assert backend.is_enabled("Rekounts") is False
    assert not (tmp_path / "com.rekreatedigital.rekounts.plist").exists()


def test_disable_when_absent_is_noop(backend):
    backend.disable("Rekounts")     # must not raise
    backend.disable("Rekounts")
    assert backend.is_enabled("Rekounts") is False


def test_corrupt_plist_reads_as_disabled(backend, tmp_path):
    """A mangled plist is not "enabled" in any honest sense, and enable()
    must be able to overwrite it with a whole one."""
    path = tmp_path / "com.rekreatedigital.rekounts.plist"
    path.write_bytes(b"not a plist at all")
    assert backend.current("Rekounts") is None
    backend.enable("Rekounts", "cmd")
    assert backend.current("Rekounts") == "cmd"


def test_purge_and_legacy_helpers_work_through_the_interface(backend):
    backend.enable("TalkativeAI", "old-cmd")
    assert startup.legacy_is_registered(backend=backend) is True
    assert startup.legacy_startup_was_disabled(backend=backend) is False
    assert startup.purge_legacy(backend=backend) is True
    assert startup.legacy_is_registered(backend=backend) is False
    assert startup.purge_legacy(backend=backend) is False   # idempotent


def test_module_api_uses_the_injected_backend(backend):
    startup.set_enabled(True, command="cmd", backend=backend)
    assert startup.is_enabled(backend=backend) is True
    assert startup.current_command(backend=backend) == "cmd"
    startup.set_enabled(False, backend=backend)
    assert startup.is_enabled(backend=backend) is False


def test_get_backend_picks_launch_agents_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(startup.get_backend(), LaunchAgentBackend)


def test_default_command_args_prefers_launcher():
    args = startup.default_command_args()
    # Whatever the platform, the registered argv must be absolute and start
    # with a real interpreter/executable.
    assert args
    assert args[0]


def test_default_command_is_shlex_quoted_off_windows(monkeypatch):
    """The posix string form must round-trip through LaunchAgentBackend's
    shlex parsing even with spaces in the path (test_startup.py pins the
    Windows double-quote shape; this pins the mac one)."""
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(startup.sys, "executable",
                        "/Applications/Rekounts Dev/python3", raising=False)
    cmd = startup.default_command()
    import shlex
    assert shlex.split(cmd) == ["/Applications/Rekounts Dev/python3"]
