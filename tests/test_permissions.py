"""macOS permission onboarding policy, with every probe faked."""
from rekounts.permissions import (
    PermissionState,
    check_permissions,
    missing_permission_messages,
)


def states(input_mon=True, access=True, mic=True):
    return check_permissions(
        platform="darwin",
        input_monitoring=lambda: input_mon,
        accessibility=lambda: access,
        microphone=lambda: mic,
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
