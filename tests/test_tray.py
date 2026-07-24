"""Tray menu freshness and update-check hardening.

Split in two: pure helpers (repo-slug parsing, no Qt runtime needed) and menu
behavior tests that spin up an offscreen QApplication so they run headless.
"""
import os

import pytest

from rekounts.ui.tray import (GITHUB_REPO, _origin_repo_slug, _resolve_repo_slug,
                              is_newer, parse_version)

# ------------------------------------------------------------- update check
def test_hardcoded_repo_slug_matches_the_origin_remote():
    """The one hardcoded network target must not drift from the real repo.

    Skipped rather than failed when git can't answer (release tarball, CI
    without the remote), which is exactly when the app falls back to the
    constant anyway.
    """
    origin = _origin_repo_slug()
    if origin is None:
        pytest.skip("no git origin available here")
    assert origin.lower() == GITHUB_REPO.lower()


def test_resolve_repo_slug_always_returns_something_usable():
    slug = _resolve_repo_slug()
    assert slug and slug.count("/") == 1


def test_frozen_exe_degrades_to_the_constant(monkeypatch):
    # A PyInstaller build has no .git next to it and often no git on PATH.
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert _origin_repo_slug() is None
    assert _resolve_repo_slug() == GITHUB_REPO


def test_missing_git_directory_degrades_to_the_constant(monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    assert _origin_repo_slug() is None


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/rekreatedigital/rekounts.git", "rekreatedigital/rekounts"),
    ("https://github.com/rekreatedigital/rekounts", "rekreatedigital/rekounts"),
    ("git@github.com:rekreatedigital/rekounts.git", "rekreatedigital/rekounts"),
    ("ssh://git@github.com/owner/repo.git", "owner/repo"),
    ("https://gitlab.com/owner/repo.git", None),
    ("", None),
])
def test_origin_url_parsing(monkeypatch, url, expected):
    import subprocess

    import rekounts.ui.tray as tray

    class _Out:
        returncode = 0
        stdout = url

    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out())
    assert tray._origin_repo_slug() == expected


def test_git_failure_is_swallowed(monkeypatch):
    import subprocess

    import rekounts.ui.tray as tray

    def boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(subprocess, "run", boom)
    assert tray._origin_repo_slug() is None
    assert tray._resolve_repo_slug() == GITHUB_REPO


# ------------------------------------------------------- release comparison
@pytest.mark.parametrize("tag, expected", [
    ("v0.3.0", (0, 3, 0)),
    ("0.3.0", (0, 3, 0)),
    ("V1.10.2", (1, 10, 2)),
    ("  v2.0  ", (2, 0)),
    ("v1.2.3-rc1", (1, 2, 3)),      # suffix ignored, not ordered
    ("1", (1,)),
    ("nightly", None),
    ("", None),
    (None, None),
    (0.3, None),                     # a JSON number where a tag was expected
])
def test_version_tags_are_parsed_or_refused(tag, expected):
    assert parse_version(tag) == expected


@pytest.mark.parametrize("candidate, current, expected", [
    ("v0.4.0", "0.3.0", True),
    ("v0.3.1", "0.3.0", True),
    ("v1.0.0", "0.9.9", True),
    ("v0.3.0", "0.3.0", False),
    ("v0.2.0", "0.3.0", False),      # a yanked latest release must not "upgrade"
    ("v0.4", "0.4.0", False),        # zero-padded, so these are the same version
    ("v0.4.1", "0.4", True),
    ("v0.10.0", "0.9.0", True),      # 10 > 9, not "1" > "9" as strings
])
def test_only_a_strictly_later_release_counts_as_newer(candidate, current, expected):
    assert is_newer(parse_version(candidate), parse_version(current)) is expected


def test_an_unparseable_version_is_never_newer():
    # Better to say nothing than to nag about an upgrade that may not exist.
    assert is_newer(None, (0, 3, 0)) is False
    assert is_newer((0, 4, 0), None) is False


# ------------------------------------------------------------ menu behavior
# Offscreen so the suite stays headless and never pops a real tray icon.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.config import Config  # noqa: E402  (after importorskip)
from rekounts.ui.tray import TrayApp  # noqa: E402

LANGUAGES = [("English", "en"), ("Spanish", "es"), ("Auto-detect", "auto")]


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def config(tmp_path):
    return Config(tmp_path / "config.json")


@pytest.fixture
def tray(app, config, monkeypatch):
    """A TrayApp whose microphone list is a fixed fake we can mutate."""
    import rekounts.ui.tray as tray_mod
    mics = ["Microphone (EMEET PIXY)", "Headset Microphone (3- SteelSeries Arctis Nova 5)"]
    monkeypatch.setattr(tray_mod, "list_microphones", lambda: list(mics))
    monkeypatch.setattr(tray_mod, "canonical_microphone_name",
                        lambda n: n if n in mics else None)

    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, languages=LANGUAGES)
    t.mics = mics
    yield t
    t.tray.hide()


def _labels(menu):
    return [a.text() for a in menu.actions()]


def _checked(menu):
    return [a.text() for a in menu.actions() if a.isChecked()]


def test_menu_is_kept_referenced_on_the_instance(tray):
    # PySide6 can garbage-collect a QMenu owned only by setContextMenu().
    assert tray.menu is not None
    assert tray.tray.contextMenu() is tray.menu


def test_submenus_are_empty_until_opened(tray):
    assert tray._mic_menu.actions() == []
    assert tray._lang_menu.actions() == []


def test_microphone_menu_lists_system_default_first_then_devices(tray):
    tray._mic_menu.aboutToShow.emit()
    assert _labels(tray._mic_menu) == ["System default"] + tray.mics


def test_microphone_menu_checks_system_default_by_default(tray):
    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == ["System default"]


def test_microphone_menu_checkmark_follows_config_changed_elsewhere(tray, config):
    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == ["System default"]

    # Settings window changes the mic behind the tray's back.
    config.set("microphone", "Microphone (EMEET PIXY)")

    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == ["Microphone (EMEET PIXY)"]


def test_microphone_menu_picks_up_a_newly_appearing_device(tray):
    tray._mic_menu.aboutToShow.emit()
    assert "Microphone (Newly Plugged)" not in _labels(tray._mic_menu)

    tray.mics.append("Microphone (Newly Plugged)")

    tray._mic_menu.aboutToShow.emit()
    assert "Microphone (Newly Plugged)" in _labels(tray._mic_menu)


def test_reopening_does_not_duplicate_entries(tray):
    for _ in range(3):
        tray._mic_menu.aboutToShow.emit()
    assert _labels(tray._mic_menu) == ["System default"] + tray.mics


def test_exactly_one_microphone_entry_is_checked(tray, config):
    config.set("microphone", "Headset Microphone (3- SteelSeries Arctis Nova 5)")
    tray._mic_menu.aboutToShow.emit()
    assert len(_checked(tray._mic_menu)) == 1


def test_unplugged_configured_mic_leaves_nothing_checked(tray, config):
    config.set("microphone", "Microphone (Unplugged)")
    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == []


def test_picking_a_microphone_writes_config_and_notifies(tray, config):
    seen = []
    tray.on_mic_changed = seen.append
    tray._mic_menu.aboutToShow.emit()

    [act] = [a for a in tray._mic_menu.actions() if a.text() == "Microphone (EMEET PIXY)"]
    act.trigger()

    assert config.get("microphone") == "Microphone (EMEET PIXY)"
    assert seen == ["Microphone (EMEET PIXY)"]
    assert config.path.exists()          # persisted, not just in memory


def test_picking_system_default_clears_the_configured_mic(tray, config):
    config.set("microphone", "Microphone (EMEET PIXY)")
    tray._mic_menu.aboutToShow.emit()

    [act] = [a for a in tray._mic_menu.actions() if a.text() == "System default"]
    act.trigger()

    assert config.get("microphone") is None


def test_a_failing_device_query_still_leaves_a_usable_menu(tray, monkeypatch):
    import rekounts.ui.tray as tray_mod

    def boom():
        raise RuntimeError("PortAudio exploded")

    monkeypatch.setattr(tray_mod, "list_microphones", boom)
    tray._mic_menu.aboutToShow.emit()
    assert _labels(tray._mic_menu) == ["System default"]


def test_language_menu_lists_every_language(tray):
    tray._lang_menu.aboutToShow.emit()
    assert _labels(tray._lang_menu) == [label for label, _ in LANGUAGES]


def test_language_menu_checkmark_follows_config_changed_elsewhere(tray, config):
    tray._lang_menu.aboutToShow.emit()
    assert _checked(tray._lang_menu) == ["English"]

    config.set("language", "es")

    tray._lang_menu.aboutToShow.emit()
    assert _checked(tray._lang_menu) == ["Spanish"]


def test_language_menu_does_not_duplicate_on_reopen(tray):
    for _ in range(3):
        tray._lang_menu.aboutToShow.emit()
    assert len(tray._lang_menu.actions()) == len(LANGUAGES)


def test_picking_a_language_writes_config(tray, config):
    seen = []
    tray.on_language_changed = seen.append
    tray._lang_menu.aboutToShow.emit()

    [act] = [a for a in tray._lang_menu.actions() if a.text() == "Auto-detect"]
    act.trigger()

    assert config.get("language") == "auto"
    assert seen == ["auto"]


def test_no_config_means_no_device_submenus(app):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None)
    try:
        assert t._mic_menu is None and t._lang_menu is None
        assert "Microphone" not in _labels(t.menu)
    finally:
        t.tray.hide()


# ------------------------------------------------- the notifications gate
# Every toast must pass one gate (the "Tray notifications" switch), so the
# tray-originated toasts (mic/language/update-check) can no longer bypass it.
def _spy_toasts(monkeypatch, t):
    shown = []
    monkeypatch.setattr(t.tray, "showMessage", lambda *a: shown.append(a))
    return shown


def test_notify_gate_suppresses_tray_originated_toasts_when_off(app, config,
                                                                monkeypatch):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, languages=LANGUAGES,
                notifications_enabled=lambda: False)
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("plain")
        t._apply_mic("Some Mic")              # used to call notify() directly
        t._apply_language("es", "Spanish")    # ditto
        t._sig.toast.emit("update result")    # the update-check worker's path
        assert shown == []
    finally:
        t.tray.hide()


def test_notify_gate_allows_toasts_when_on(app, config, monkeypatch):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, languages=LANGUAGES,
                notifications_enabled=lambda: True)
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("hello")
        assert shown == [("Rekounts", "hello")]
    finally:
        t.tray.hide()


def test_notify_defaults_to_shown_without_a_provider(tray, monkeypatch):
    shown = _spy_toasts(monkeypatch, tray)
    tray.notify("hi")
    assert shown == [("Rekounts", "hi")]


def test_notify_gate_is_read_live(app, config, monkeypatch):
    state = {"on": False}
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, notifications_enabled=lambda: state["on"])
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("first")           # gate off -> dropped
        state["on"] = True
        t.notify("second")          # gate flipped on with nothing rebuilt
        assert shown == [("Rekounts", "second")]
    finally:
        t.tray.hide()


def test_a_broken_gate_still_shows_the_message(app, config, monkeypatch):
    def boom():
        raise RuntimeError("gate exploded")

    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, notifications_enabled=boom)
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("must survive")
        assert shown == [("Rekounts", "must survive")]
    finally:
        t.tray.hide()


# ------------------------------------------------- the update check, faked
# The HTTP is faked at urllib, not at fetch_latest_release, so these also cover
# the request headers, the JSON decode, and what happens to a malformed body.
import json  # noqa: E402
import urllib.request  # noqa: E402

import rekounts.ui.tray as tray_mod  # noqa: E402

INSTALLED = "0.3.0"     # pinned so a real version bump cannot rewrite these tests


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def github(monkeypatch):
    """Stand in for api.github.com. Set .release, or .error to fail the call."""

    class _Fake:
        release = {"tag_name": "v0.3.0",
                   "html_url": "https://github.com/rekreatedigital/rekounts/releases/tag/v0.3.0"}
        error = None
        body = None
        requests = []

        def urlopen(self, req, timeout=None):
            self.requests.append(req)
            if self.error:
                raise self.error
            payload = (self.body if self.body is not None
                       else json.dumps(self.release).encode("utf-8"))
            return _FakeResponse(payload)

    fake = _Fake()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(tray_mod, "__version__", INSTALLED)
    # Never shell out to git from these tests: the answer is the constant.
    monkeypatch.setattr(tray_mod, "_resolve_repo_slug", lambda: GITHUB_REPO)
    return fake


@pytest.fixture
def updater(app, config, monkeypatch, github):
    """A TrayApp with its toasts spied on and the network faked."""
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config)
    t.shown = []
    monkeypatch.setattr(t.tray, "showMessage", lambda *a: t.shown.append(a))
    yield t
    t.tray.hide()


def _messages(t):
    return [message for _title, message in t.shown]


def test_the_check_asks_for_the_latest_release_not_the_latest_commit(updater, github):
    updater._fetch_latest()
    [request] = github.requests
    assert request.full_url == (
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
    assert "commits" not in request.full_url


def test_the_request_identifies_itself_and_asks_for_the_api_media_type(updater,
                                                                       github):
    updater._fetch_latest()
    [request] = github.requests
    assert request.get_header("User-agent") == f"Rekounts/{INSTALLED}"
    assert request.get_header("Accept") == "application/vnd.github+json"


def test_a_newer_release_is_announced_with_both_versions(updater, github):
    github.release = {"tag_name": "v0.4.0", "html_url": "https://example.test/rel"}
    updater._fetch_latest()
    [message] = _messages(updater)
    assert "0.4.0" in message and INSTALLED in message


def test_the_update_toast_is_clickable_and_opens_the_release_page(updater, github,
                                                                  monkeypatch):
    opened = []
    monkeypatch.setattr(tray_mod.webbrowser, "open", opened.append)
    # The click handler hands off to a thread; run it inline so the test is
    # deterministic instead of racing a daemon thread.
    monkeypatch.setattr(tray_mod.threading, "Thread",
                        lambda target, args=(), daemon=None: _Inline(target, args))

    github.release = {"tag_name": "v0.9.0", "html_url": "https://example.test/rel"}
    updater._fetch_latest()
    updater.tray.messageClicked.emit()

    assert opened == ["https://example.test/rel"]


class _Inline:
    """A Thread stand-in that just runs the target when started."""

    def __init__(self, target, args):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def test_an_ordinary_toast_is_not_clickable(updater, monkeypatch):
    opened = []
    monkeypatch.setattr(tray_mod.webbrowser, "open", opened.append)

    updater.notify("Settings applied.")
    updater.tray.messageClicked.emit()

    assert opened == []


def test_a_stale_release_link_does_not_survive_the_next_toast(updater, github,
                                                              monkeypatch):
    opened = []
    monkeypatch.setattr(tray_mod.webbrowser, "open", opened.append)

    github.release = {"tag_name": "v0.9.0", "html_url": "https://example.test/rel"}
    updater._fetch_latest()
    updater.notify("Microphone set to system default.")   # a later, unrelated toast
    updater.tray.messageClicked.emit()

    assert opened == []


def test_being_up_to_date_says_so_when_the_user_asked(updater, github):
    github.release = {"tag_name": f"v{INSTALLED}", "html_url": "https://example.test"}
    updater._fetch_latest()
    [message] = _messages(updater)
    assert "latest release" in message


def test_an_older_release_than_the_installed_build_is_not_an_upgrade(updater,
                                                                     github):
    # e.g. running a build from master that is ahead of the last tag.
    github.release = {"tag_name": "v0.1.0", "html_url": "https://example.test"}
    updater._fetch_latest()
    assert "available" not in " ".join(_messages(updater))


def test_an_unparseable_tag_is_reported_rather_than_guessed_at(updater, github):
    github.release = {"tag_name": "nightly", "html_url": "https://example.test"}
    updater._fetch_latest()
    [message] = _messages(updater)
    assert "nightly" in message
    assert "available" not in message


def test_a_release_without_a_page_falls_back_to_the_releases_url(updater, github,
                                                                 monkeypatch):
    opened = []
    monkeypatch.setattr(tray_mod.webbrowser, "open", opened.append)
    monkeypatch.setattr(tray_mod.threading, "Thread",
                        lambda target, args=(), daemon=None: _Inline(target, args))

    github.release = {"tag_name": "v0.9.0"}          # html_url absent
    updater._fetch_latest()
    updater.tray.messageClicked.emit()

    assert opened == [f"https://github.com/{GITHUB_REPO}/releases/latest"]


def test_a_network_failure_is_reported_once_and_never_raises(updater, github):
    github.error = OSError("no route to host")
    updater._fetch_latest()
    [message] = _messages(updater)
    assert "Could not reach GitHub" in message


def test_a_malformed_body_is_treated_like_any_other_failure(updater, github):
    github.body = b"<html>rate limited</html>"
    updater._fetch_latest()
    [message] = _messages(updater)
    assert "Could not reach GitHub" in message


# --- the opt-in automatic check ---------------------------------------------
def test_the_automatic_check_is_off_by_default(app, config, github):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config)
    try:
        assert config.get("auto_check_updates") is False
        assert t._auto_timer is None
        assert github.requests == []      # nothing was fetched by constructing it
    finally:
        t.tray.hide()


def test_switching_it_on_schedules_exactly_one_check(app, config, github):
    config.set("auto_check_updates", True)
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config)
    try:
        assert t._auto_timer is not None
        assert t._auto_timer.isSingleShot()
        assert t._auto_timer.isActive()
    finally:
        t.tray.hide()


def test_a_tray_without_config_never_checks_automatically(app, github):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None)
    try:
        assert t._auto_check_enabled() is False
        assert t._auto_timer is None
    finally:
        t.tray.hide()


def test_a_host_supplied_check_is_never_run_automatically(app, config, github):
    """If the app replaced the manual check, we must not fire our own behind it."""
    config.set("auto_check_updates", True)
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, on_check_updates=lambda: None)
    try:
        assert t._auto_timer is None
    finally:
        t.tray.hide()


def test_the_silent_check_says_nothing_when_there_is_no_update(updater, github):
    github.release = {"tag_name": f"v{INSTALLED}", "html_url": "https://example.test"}
    updater._fetch_latest(silent=True)
    assert updater.shown == []


def test_the_silent_check_says_nothing_when_the_network_is_down(updater, github):
    github.error = OSError("offline")
    updater._fetch_latest(silent=True)
    assert updater.shown == []


def test_the_silent_check_still_announces_a_real_update(updater, github):
    github.release = {"tag_name": "v1.0.0", "html_url": "https://example.test/rel"}
    updater._fetch_latest(silent=True)
    [message] = _messages(updater)
    assert "1.0.0" in message


def test_clicking_the_menu_item_runs_a_loud_check(updater, github, monkeypatch):
    """QAction.triggered passes `checked`, which must not land in `silent`.

    Spied at _fetch_latest, the seam the real _check_for_updates resolves when it
    is called — the menu action holds its handler from construction time, so
    replacing _check_for_updates here would test nothing.
    """
    calls = []
    monkeypatch.setattr(updater, "_fetch_latest", lambda silent=False: calls.append(silent))
    monkeypatch.setattr(tray_mod.threading, "Thread",
                        lambda target, args=(), daemon=None: _Inline(target, args))

    [action] = [a for a in updater.menu.actions() if a.text() == "Check for Updates"]
    action.trigger()

    assert calls == [False]


def test_a_loud_check_announces_itself_before_going_to_the_network(updater,
                                                                   monkeypatch):
    monkeypatch.setattr(tray_mod.threading, "Thread",
                        lambda target, args=(), daemon=None: _Inline(target, args))
    updater._check_for_updates()
    assert "Checking GitHub" in _messages(updater)[0]


def test_a_silent_check_announces_nothing_up_front(updater, github, monkeypatch):
    monkeypatch.setattr(tray_mod.threading, "Thread",
                        lambda target, args=(), daemon=None: _Inline(target, args))
    github.release = {"tag_name": f"v{INSTALLED}", "html_url": "https://example.test"}
    updater._check_for_updates(silent=True)
    assert updater.shown == []


def test_a_parseable_but_non_dict_body_reads_as_unreachable(updater, github):
    # An exotic proxy/rate-limit shape: valid JSON that isn't an object. Must
    # fail soft like any network error, never kill the worker thread.
    github.body = json.dumps(["not", "a", "release"]).encode("utf-8")
    updater._fetch_latest()
    assert _messages(updater) == ["Could not reach GitHub to check for updates."]


# ------------------------------------------------------------- scratchpad
def _entry(t):
    return next((a for a in t.menu.actions() if a.text() == "Open Scratchpad"), None)


def test_no_scratchpad_entry_when_the_pad_is_not_wired(tray):
    """Backward compatibility: an older caller gets the menu it always had."""
    assert _entry(tray) is None


def test_scratchpad_entry_opens_the_pad(app, config):
    opened = []
    t = TrayApp(app, lambda: None, lambda: None, config=config,
                on_open_scratchpad=lambda: opened.append(True))
    _entry(t).trigger()
    assert opened == [True]


def test_the_entry_hides_when_the_setting_is_off(app, config):
    """Instant apply: flipping the switch must show in the very next open of
    the menu, not at the next launch."""
    config.set("scratchpad_enabled", True)
    t = TrayApp(app, lambda: None, lambda: None, config=config,
                on_open_scratchpad=lambda: None,
                scratchpad_enabled=lambda: bool(config.get("scratchpad_enabled")))
    assert _entry(t).isVisible()

    config.set("scratchpad_enabled", False)
    t.menu.aboutToShow.emit()
    assert not _entry(t).isVisible()

    config.set("scratchpad_enabled", True)
    t.menu.aboutToShow.emit()
    assert _entry(t).isVisible()


def test_a_broken_gate_leaves_the_entry_reachable(app, config):
    """Failing closed would hide the only route the user has to their notes."""
    def boom():
        raise RuntimeError("no config")

    t = TrayApp(app, lambda: None, lambda: None, config=config,
                on_open_scratchpad=lambda: None, scratchpad_enabled=boom)
    assert _entry(t).isVisible()
