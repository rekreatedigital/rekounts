"""Tests for launch-on-login management.

The Windows registry is mocked with an in-memory fake so these run on any OS and
never touch the real HKCU Run key.
"""
import pytest

import rekounts.startup as startup
from rekounts.startup import WindowsRegistryBackend, StartupBackend


# --- an in-memory fake of the winreg subset we use --------------------------

class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_BINARY = 3

    def __init__(self):
        # {(root, subkey): {value_name: value}}
        self.store = {}

    class _Handle:
        def __init__(self, key):
            self.key = key

    def CreateKey(self, root, subkey):
        self.store.setdefault((root, subkey), {})
        return self._Handle((root, subkey))

    def OpenKey(self, root, subkey, reserved=0, access=0):
        if (root, subkey) not in self.store:
            raise FileNotFoundError(2, "key not found")
        return self._Handle((root, subkey))

    def SetValueEx(self, handle, name, reserved, type_, value):
        self.store[handle.key][name] = value

    def QueryValueEx(self, handle, name):
        values = self.store[handle.key]
        if name not in values:
            raise FileNotFoundError(2, "value not found")
        return values[name], self.REG_SZ

    def DeleteValue(self, handle, name):
        values = self.store[handle.key]
        if name not in values:
            raise FileNotFoundError(2, "value not found")
        del values[name]

    def CloseKey(self, handle):
        pass


@pytest.fixture
def backend():
    return WindowsRegistryBackend(winreg_module=FakeWinreg())


# --- WindowsRegistryBackend against the mocked registry ---------------------

def test_starts_disabled(backend):
    assert backend.is_enabled("Rekounts") is False
    assert backend.current("Rekounts") is None


def test_enable_then_is_enabled(backend):
    backend.enable("Rekounts", '"C:\\app\\pythonw.exe" "C:\\app\\launch.py"')
    assert backend.is_enabled("Rekounts") is True
    assert backend.current("Rekounts") == '"C:\\app\\pythonw.exe" "C:\\app\\launch.py"'


def test_enable_is_idempotent_and_updates_command(backend):
    backend.enable("Rekounts", "cmd-one")
    backend.enable("Rekounts", "cmd-two")
    assert backend.current("Rekounts") == "cmd-two"


def test_disable_removes_entry(backend):
    backend.enable("Rekounts", "cmd")
    backend.disable("Rekounts")
    assert backend.is_enabled("Rekounts") is False


def test_disable_when_absent_is_noop(backend):
    # No Run key created yet -> must not raise.
    backend.disable("Rekounts")
    assert backend.is_enabled("Rekounts") is False


def test_disable_twice_is_noop(backend):
    backend.enable("Rekounts", "cmd")
    backend.disable("Rekounts")
    backend.disable("Rekounts")
    assert backend.is_enabled("Rekounts") is False


def test_other_run_values_are_untouched(backend):
    wr = backend._winreg
    key = wr.CreateKey(wr.HKEY_CURRENT_USER, backend._run_key)
    wr.SetValueEx(key, "SomeOtherApp", 0, wr.REG_SZ, "other")
    backend.enable("Rekounts", "mine")
    backend.disable("Rekounts")
    # Removing our value leaves the neighbour's intact.
    assert wr.QueryValueEx(key, "SomeOtherApp")[0] == "other"


# --- StartupApproved: Task Manager's Startup-tab enable/disable flag ---------

def _set_approval(backend, name, first_byte):
    """Write a StartupApproved\\Run value like Task Manager does (12 bytes; the
    first encodes the state, even=enabled / 0x03=disabled)."""
    wr = backend._winreg
    key = wr.CreateKey(wr.HKEY_CURRENT_USER, backend._approved_key)
    wr.SetValueEx(key, name, 0, wr.REG_BINARY, bytes([first_byte]) + b"\x00" * 11)
    wr.CloseKey(key)


def _approval_value(backend, name):
    wr = backend._winreg
    return backend._winreg.store.get(
        (wr.HKEY_CURRENT_USER, backend._approved_key), {}).get(name)


def test_task_manager_disable_reads_as_not_enabled(backend):
    # Registered in Run, but the user switched us OFF in Task Manager -> Windows
    # skips us at login, so is_enabled() must say False even though a command
    # is still registered.
    backend.enable("Rekounts", "cmd")
    _set_approval(backend, "Rekounts", 0x03)
    assert backend.is_enabled("Rekounts") is False
    assert backend.current("Rekounts") == "cmd"      # the command is still there


def test_task_manager_enabled_flag_reads_as_enabled(backend):
    backend.enable("Rekounts", "cmd")
    _set_approval(backend, "Rekounts", 0x02)
    assert backend.is_enabled("Rekounts") is True


@pytest.mark.parametrize("first_byte, enabled", [
    (0x02, True), (0x06, True), (0x03, False), (0x0b, False),
])
def test_approval_first_byte_parity_decides_enabled(backend, first_byte, enabled):
    backend.enable("Rekounts", "cmd")
    _set_approval(backend, "Rekounts", first_byte)
    assert backend.is_enabled("Rekounts") is enabled


def test_missing_approval_key_counts_as_enabled(backend):
    # Never toggled in Task Manager -> the default is enabled.
    backend.enable("Rekounts", "cmd")
    assert backend.is_enabled("Rekounts") is True


def test_enable_clears_a_task_manager_disable(backend):
    backend.enable("Rekounts", "cmd")
    _set_approval(backend, "Rekounts", 0x03)          # user disabled us in Task Manager
    assert backend.is_enabled("Rekounts") is False

    backend.enable("Rekounts", "cmd")                 # toggling ON must actually take
    assert backend.is_enabled("Rekounts") is True
    assert _approval_value(backend, "Rekounts") is None  # disable flag cleared


def test_clear_approval_leaves_other_apps_flags_alone(backend):
    _set_approval(backend, "Rekounts", 0x03)
    _set_approval(backend, "SomeOtherApp", 0x03)
    backend.enable("Rekounts", "cmd")
    assert _approval_value(backend, "Rekounts") is None
    assert _approval_value(backend, "SomeOtherApp") is not None


# --- the legacy name's Task Manager state, read before the upgrade purge -----

def test_legacy_task_manager_disable_is_readable_before_the_purge(backend):
    """purge_legacy deletes the flag, so the reconcile must be able to ask
    "did the user switch the OLD app off in Task Manager?" first."""
    backend.enable("TalkativeAI", "cmd")
    _set_approval(backend, "TalkativeAI", 0x03)
    assert startup.legacy_startup_was_disabled(backend=backend) is True


def test_legacy_untouched_or_enabled_in_task_manager_reads_false(backend):
    assert startup.legacy_startup_was_disabled(backend=backend) is False
    backend.enable("TalkativeAI", "cmd")
    assert startup.legacy_startup_was_disabled(backend=backend) is False
    _set_approval(backend, "TalkativeAI", 0x02)
    assert startup.legacy_startup_was_disabled(backend=backend) is False


def test_backends_without_an_external_switch_report_not_disabled():
    # DictBackend (defined below) has no Task Manager equivalent; the base
    # class must answer False rather than raise.
    assert startup.legacy_startup_was_disabled(backend=DictBackend()) is False


# --- module-level API delegates to whatever backend is passed ---------------

class DictBackend(StartupBackend):
    def __init__(self):
        self.entries = {}

    def enable(self, name, command):
        self.entries[name] = command

    def disable(self, name):
        self.entries.pop(name, None)

    def current(self, name):
        return self.entries.get(name)


def test_module_api_enable_disable_roundtrip():
    b = DictBackend()
    assert startup.is_enabled(backend=b) is False
    startup.enable("some-command", backend=b)
    assert startup.is_enabled(backend=b) is True
    assert startup.current_command(backend=b) == "some-command"
    startup.disable(backend=b)
    assert startup.is_enabled(backend=b) is False


def test_enable_without_command_uses_default(monkeypatch):
    b = DictBackend()
    monkeypatch.setattr(startup, "default_command", lambda: "DEFAULT-CMD")
    startup.enable(backend=b)
    assert startup.current_command(backend=b) == "DEFAULT-CMD"


def test_set_enabled_toggles():
    b = DictBackend()
    startup.set_enabled(True, "cmd", backend=b)
    assert startup.is_enabled(backend=b) is True
    startup.set_enabled(False, backend=b)
    assert startup.is_enabled(backend=b) is False


# --- default_command formatting ---------------------------------------------

def test_default_command_frozen(monkeypatch):
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(startup.sys, "executable", r"C:\dist\Rekounts.exe",
                        raising=False)
    assert startup.default_command() == r'"C:\dist\Rekounts.exe"'


def test_default_command_from_source_uses_launcher(monkeypatch, tmp_path):
    # Lay out a fake repo: <root>/launch.py and <root>/.venv/Scripts/pythonw.exe
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    pythonw = scripts / "pythonw.exe"
    pythonw.write_text("")
    (tmp_path / "launch.py").write_text("")
    pkg_file = tmp_path / "rekounts" / "startup.py"
    pkg_file.parent.mkdir()
    pkg_file.write_text("")

    monkeypatch.setattr(startup.sys, "frozen", False, raising=False)
    monkeypatch.setattr(startup.sys, "executable", str(pythonw), raising=False)
    monkeypatch.setattr(startup.os.path, "abspath", lambda _p: str(pkg_file))

    cmd = startup.default_command()
    assert cmd == '"{}" "{}"'.format(pythonw, tmp_path / "launch.py")
