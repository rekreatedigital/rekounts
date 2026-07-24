"""The Inno Setup script, checked against the Python it has to agree with.

``installer/rekounts.iss`` cannot import anything: it restates the registry key,
the value name, the single-instance mutex and the AppUserModelID that the app
defines in Python. Those restatements are the whole risk of the installer — get
one wrong and the "start at sign-in" checkbox writes an entry the app's own
Settings switch cannot see, or the close-app prompt silently stops working, and
nothing else in the build fails.

So the .iss is parsed here and compared to the source of truth in the package.
These tests are text-level on purpose: they run everywhere, including the Linux
CI box that has no Inno Setup and no Windows registry.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ISS = REPO_ROOT / "installer" / "rekounts.iss"


@pytest.fixture(scope="module")
def script() -> str:
    if not ISS.is_file():
        pytest.fail("installer/rekounts.iss is missing")
    return ISS.read_text(encoding="utf-8")


def _define(script: str, name: str) -> str:
    """The value of an ISPP  #define NAME "value"  line."""
    m = re.search(rf'^#define\s+{name}\s+"([^"]*)"\s*$', script, re.M)
    assert m, f"#define {name} not found in rekounts.iss"
    return m.group(1)


def _setting(script: str, name: str) -> str:
    """The value of a  Name=value  line in [Setup]."""
    m = re.search(rf"^{name}=(.*)$", script, re.M)
    assert m, f"[Setup] entry {name} not found in rekounts.iss"
    return m.group(1).strip()


# --- the launch-at-login mechanism must be the app's, not a second one ------
def test_the_installer_writes_the_registry_key_the_app_reads(script):
    from rekounts.startup import _RUN_KEY

    assert _define(script, "RunKey") == _RUN_KEY


def test_the_installer_clears_the_same_task_manager_flag_the_app_does(script):
    from rekounts.startup import _APPROVED_KEY

    assert _define(script, "StartupApproved") == _APPROVED_KEY


def test_the_installer_uses_the_app_s_run_value_name(script):
    from rekounts.startup import APP_NAME

    assert _define(script, "RunValueName") == APP_NAME


def test_the_installer_writes_the_command_the_app_would_write(script):
    """A frozen build registers a quoted absolute path to the .exe, nothing more.

    If startup.default_command() ever grows an argument, the installer's value
    stops matching what the app writes, and the two will fight on every launch.
    """
    from rekounts import startup

    command = re.search(r'ValueData:\s*"""\{app\}\\\{#AppExeName\}"""', script)
    assert command, "the Run value is not a plain quoted path to the exe"
    # And the app's own frozen-mode command has the same shape.
    assert startup._quote("C:\\x\\Rekounts.exe") == '"C:\\x\\Rekounts.exe"'


def test_uninstall_removes_the_startup_entry_however_it_got_there(script):
    # Not just the installer's own [Registry] entry: the app's Settings switch
    # can have written it, and a Run entry pointing at a deleted exe is retried
    # by Windows at every sign-in.
    assert "procedure RemoveStartupEntry" in script
    assert re.search(r"if CurUninstallStep = usUninstall then\s*\n\s*RemoveStartupEntry;",
                     script)


def test_uninstall_leaves_another_copy_s_startup_entry_alone(script):
    """A portable ZIP copy uses the same Run value name from a different folder.

    Uninstalling the installed copy must not switch that one's autostart off, so
    the value is only deleted when it names something inside {app}.
    """
    body = script[script.index("procedure RemoveStartupEntry"):]
    body = body[:body.index("procedure InitializeWizard")]
    assert "RegQueryStringValue" in body
    assert re.search(r"if Pos\(Lowercase\(ExpandConstant\('\{app\}'\)\) \+ '\\', "
                     r"Lowercase\(Command\)\) = 0 then\s*\n\s*Exit;", body)


# --- the close-app prompt ---------------------------------------------------
def test_the_close_app_prompt_watches_the_app_s_real_mutex(script):
    from rekounts.__main__ import _MUTEX_NAME

    assert _define(script, "AppMutexName") == _MUTEX_NAME
    assert _setting(script, "AppMutex") == "{#AppMutexName}"


def test_shortcuts_carry_the_app_s_own_taskbar_identity(script):
    from rekounts.ui.branding import APP_USER_MODEL_ID

    assert _define(script, "AppUserModelID") == APP_USER_MODEL_ID
    # Both shortcuts, or a pinned one ends up a separate taskbar button.
    assert script.count('AppUserModelID: "{#AppUserModelID}"') == 2


# --- per-user, never elevated ----------------------------------------------
def test_the_installer_never_asks_for_admin(script):
    assert _setting(script, "PrivilegesRequired") == "lowest"
    # No override directive, so not even a command line can turn this into an
    # admin install. (Matched as a directive, not a substring — the script's
    # comments explain the omission and would otherwise satisfy the check.)
    assert not re.search(r"^PrivilegesRequiredOverridesAllowed=", script, re.M)


def test_it_installs_into_the_per_user_programs_folder(script):
    assert _setting(script, "DefaultDirName") == r"{userpf}\{#AppName}"


def test_the_licence_page_shows_the_project_licence(script):
    licence = REPO_ROOT / _setting(script, "LicenseFile").replace("..\\", "")
    assert licence.is_file()
    assert "GNU GENERAL PUBLIC LICENSE" in licence.read_text(encoding="utf-8")[:2000]


def test_the_install_directory_page_is_shown(script):
    assert _setting(script, "DisableDirPage") == "no"


# --- user data survives unless explicitly sacrificed ------------------------
def test_the_uninstaller_deletes_user_data_only_when_it_was_asked_to(script):
    body = script[script.index("[Code]"):]
    deletions = re.findall(r"DelTree\((.*)", body)
    assert len(deletions) == 1, "more than one place deletes a tree"
    guarded = re.search(
        r"if \(CurUninstallStep = usPostUninstall\) and RemoveUserDataChosen then\s*\n"
        r"\s*DelTree\(UserDataDir", body)
    assert guarded, "the user-data deletion is not guarded by the checkbox"


def test_nothing_outside_the_code_section_points_at_user_data(script):
    """[UninstallDelete] must never mention %APPDATA% — it runs unconditionally."""
    sections = script[script.index("[Files]"):script.index("[Code]")]
    assert "{userappdata}" not in sections


def test_a_silent_uninstall_keeps_user_data(script):
    # Nobody to ask, so the answer has to be the one that destroys nothing.
    assert re.search(r"if UninstallSilent then\s*\n\s*Exit;", script)
    assert re.search(r"RemoveUserDataChosen := False;", script)


def test_installing_never_touches_user_data(script):
    """The install path has no business reading or writing %APPDATA%.

    Only the uninstaller's optional cleanup may mention it — via UserDataDir().
    """
    assert script.count("{userappdata}") == 1
    assert "UserDataDir" in script[script.index("[Code]"):]


# --- upgrades ---------------------------------------------------------------
def test_the_app_identity_is_pinned_so_upgrades_replace_rather_than_duplicate(script):
    # The leading brace is doubled because Inno reads a single "{" as the start
    # of a constant; the GUID itself is the remaining {........-....-...}.
    app_id = _setting(script, "AppId")
    assert re.fullmatch(r"\{\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}",
                        app_id), app_id


def test_an_existing_startup_choice_is_carried_across_an_upgrade(script):
    # Otherwise re-running the installer silently switches launch-at-login off
    # for anyone who had it on.
    assert re.search(r"if RegValueExists\(HKEY_CURRENT_USER, '\{#RunKey\}', "
                     r"'\{#RunValueName\}'\) then\s*\n\s*WizardSelectTasks\("
                     r"'startupentry'\);", script)


def test_the_output_name_carries_the_version(script):
    assert _setting(script, "OutputBaseFilename") == "{#AppName}-Setup-{#AppVersion}"
    # Read from the built exe, which Rekounts.spec stamps from the one version
    # literal — so the file name cannot disagree with the app inside it.
    assert "GetStringFileInfo(AppExe, PRODUCT_VERSION)" in script


def test_the_wizard_images_the_script_references_exist(script):
    pattern = _setting(script, "WizardSmallImageFile")
    matches = list(ISS.parent.glob(pattern))
    assert matches, f"no installer/{pattern} — run tools/make_icon.py"


def test_the_setup_icon_is_the_committed_app_icon(script):
    assert _setting(script, "SetupIconFile") == r"..\assets\icon.ico"
    assert (REPO_ROOT / "assets" / "icon.ico").is_file()


def test_uninstall_never_wildcard_deletes_the_install_dir(script):
    """[UninstallDelete] must scope to _internal: a user who installs into a
    folder that already holds other files keeps those files on uninstall."""
    section = script.split("[UninstallDelete]")[1].split("[Code]")[0]
    assert 'Name: "{app}\_internal"' in section
    assert 'Type: dirifempty; Name: "{app}"' in section
    assert 'filesandordirs; Name: "{app}"\n' not in section


def test_run_value_removal_is_code_only_no_uninsdeletevalue(script):
    # uninsdeletevalue would delete a portable copy's autostart that the [Code]
    # guard deliberately preserves; removal must go through RemoveStartupEntry.
    assert "uninsdeletevalue" not in script
