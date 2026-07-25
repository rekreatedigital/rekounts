"""macOS permission onboarding policy, with every probe faked."""
from rekounts.permissions import (
    PermissionState,
    check_permissions,
    missing_permission_messages,
)


def states(input_mon=True, access=True, mic=True, frozen=True):
    return check_permissions(
        platform="darwin",
        input_monitoring=lambda: input_mon,
        accessibility=lambda: access,
        microphone=lambda: mic,
        frozen=frozen,
    )


def test_non_darwin_has_nothing_to_check():
    assert check_permissions(platform="win32") == []
    assert check_permissions(platform="linux") == []
    assert missing_permission_messages([]) == []


def test_all_granted_is_silent():
    assert missing_permission_messages(states()) == []


def test_each_denial_produces_one_actionable_message():
    msgs = missing_permission_messages(states(input_mon=False))
    assert len(msgs) == 1
    assert "Input Monitoring" in msgs[0]

    msgs = missing_permission_messages(states(access=False))
    assert len(msgs) == 1
    assert "Accessibility" in msgs[0]

    msgs = missing_permission_messages(states(mic=False))
    assert len(msgs) == 1
    assert "icrophone" in msgs[0]


def test_all_denied_reports_all_three():
    msgs = missing_permission_messages(
        states(input_mon=False, access=False, mic=False))
    assert len(msgs) == 3


def test_unknown_is_not_reported_as_missing():
    """None = unreadable, or a consent macOS will prompt for on first use.
    Warning about it would be a false alarm on every machine we cannot read."""
    msgs = missing_permission_messages(
        states(input_mon=None, access=None, mic=None))
    assert msgs == []


def test_probe_exceptions_read_as_unknown_not_denied():
    def boom():
        raise RuntimeError("no pyobjc here")

    result = check_permissions(platform="darwin", input_monitoring=boom,
                               accessibility=boom, microphone=boom)
    assert [s.granted for s in result] == [None, None, None]
    assert missing_permission_messages(result) == []


def test_states_carry_guidance_text():
    for s in states(input_mon=False, access=False, mic=False):
        assert isinstance(s, PermissionState)
        assert "System Settings" in s.guidance


# ------------------------------------- which app the user is told to enable
# macOS grants a TCC consent to the running BUNDLE. Packaged, that is
# Rekounts.app. From source it is whatever launched Python — the terminal — so
# "Rekounts" is not in the list at all, and telling someone to look for it is
# how a working app gets diagnosed as broken.
ALL_DENIED = dict(input_mon=False, access=False, mic=False)


def test_the_packaged_app_keeps_the_wording_that_is_right_for_it():
    msgs = missing_permission_messages(states(frozen=True, **ALL_DENIED))
    assert msgs == [
        "Rekounts can't see the dictation hotkey. Enable Rekounts under System "
        "Settings > Privacy & Security > Input Monitoring, then quit and "
        "reopen Rekounts.",
        "Rekounts can't paste dictated text. Enable Rekounts under System "
        "Settings > Privacy & Security > Accessibility, then quit and reopen "
        "Rekounts.",
        "Rekounts can't hear you: microphone access is denied. Enable Rekounts "
        "under System Settings > Privacy & Security > Microphone.",
    ]


def test_a_source_run_never_tells_you_to_find_rekounts_in_the_list():
    for msg in missing_permission_messages(states(frozen=False, **ALL_DENIED)):
        assert "Enable Rekounts under" not in msg
        # ...and says so outright, because the empty list is the whole trap.
        assert "will not appear in the list" in msg
        assert "your terminal" in msg


def test_both_builds_still_name_the_pane_and_the_symptom():
    for frozen in (True, False):
        msgs = missing_permission_messages(states(frozen=frozen, **ALL_DENIED))
        panes = ["Input Monitoring", "Accessibility", "Microphone"]
        symptoms = ["see the dictation hotkey", "paste dictated text",
                    "can't hear you"]
        for msg, pane, symptom in zip(msgs, panes, symptoms):
            assert pane in msg
            assert symptom in msg


def test_the_build_is_read_from_this_process_when_not_injected():
    """Production passes nothing. Running the suite is a source run, so the
    default must be the source wording — never the .app's."""
    real = check_permissions(platform="darwin",
                             input_monitoring=lambda: False,
                             accessibility=lambda: True,
                             microphone=lambda: True)
    assert "Enable Rekounts under" not in real[0].guidance


def test_no_terminal_is_ever_named():
    """Working out WHICH terminal needs native APIs this port has not earned
    yet — a wrong guess is worse than the generic instruction."""
    for msg in missing_permission_messages(states(frozen=False, **ALL_DENIED)):
        for guess in ("iTerm", "Terminal.app", "VS Code", "Warp"):
            assert guess not in msg
