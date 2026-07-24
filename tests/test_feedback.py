"""Feedback without a backend: what the links carry, and what they never carry.

Two halves. The first is pure — scrubbing, the diagnostics block and the two
URLs need no display — and it is where the privacy promise is actually pinned
down: a transcript, a user name and a home path must not survive into anything
this feature produces. The second half spins up an offscreen QApplication for
the review dialog.
"""
import os
import subprocess
import sys

import pytest

from rekounts import feedback
from rekounts.config import Config

SLUG = "rekreatedigital/rekounts"

# Stand-ins for the things that must never leave. Distinctive enough that a
# substring search for them is meaningful.
TRANSCRIPT = "I dictated my bank password out loud and it was hunter2"
SCRATCHPAD = "Scratchpad note: call Dr Halloran back about the results"
DICTIONARY = "Rekreate Digital"
USERNAME = "Ryank"
MACHINE = "RYANK-DESKTOP"
HOME = r"C:\Users\Ryank"


@pytest.fixture
def identity(monkeypatch):
    """Pin the machine's identity so the scrubber has a known target.

    Deliberately NOT ``APPDATA``: the suite pins that to a throwaway directory
    (tests/conftest.py) and everything that writes a file relies on it.
    """
    monkeypatch.setenv("USERNAME", USERNAME)
    monkeypatch.setenv("USERPROFILE", HOME)
    monkeypatch.setenv("COMPUTERNAME", MACHINE)
    monkeypatch.setattr(feedback.platform, "node", lambda: MACHINE)
    monkeypatch.setattr(feedback.getpass, "getuser", lambda: USERNAME)
    monkeypatch.setattr(feedback.Path, "home", classmethod(lambda cls: cls(HOME)))


@pytest.fixture
def config(tmp_path):
    return Config(path=tmp_path / "config.json")


# ================================================================= scrubbing
def test_the_home_path_becomes_a_generic_one(identity):
    line = rf"log file: {HOME}\AppData\Roaming\Rekounts\logs\rekounts.log"
    out = feedback.scrub(line)
    assert HOME not in out
    assert r"%USERPROFILE%\AppData\Roaming\Rekounts\logs" in out


def test_the_user_and_machine_names_are_replaced(identity):
    out = feedback.scrub(f"{USERNAME} on {MACHINE} reports a crash")
    assert USERNAME not in out
    assert MACHINE not in out
    assert out == "<user> on <machine> reports a crash"


def test_case_does_not_save_a_name_from_the_scrubber(identity):
    out = feedback.scrub(r"c:\users\RYANK\Desktop and ryanK said so")
    assert "ryank" not in out.lower()


def test_somebody_elses_profile_path_is_scrubbed_too(identity):
    # A path that is not this machine's home — the identity replacements would
    # miss it, so the generic pattern has to catch it.
    out = feedback.scrub(r"could not read D:\Users\Jenny\config.json")
    assert "Jenny" not in out
    assert r"D:\Users\<user>\config.json" in out


def test_posix_home_paths_are_scrubbed(identity):
    assert feedback.scrub("/Users/jenny/Library/x") == "/Users/<user>/Library/x"
    assert feedback.scrub("/home/jenny/.config") == "/home/<user>/.config"


def test_scrub_survives_empty_and_none():
    assert feedback.scrub("") == ""
    assert feedback.scrub(None) == ""


# =============================================================== diagnostics
def test_the_block_names_the_app_the_system_and_the_settings(config):
    config.set("model", "medium")
    config.set("device", "cpu")
    config.set("insertion_mode", "keystroke")
    block = feedback.collect(config)
    assert "Rekounts" in block
    assert "medium" in block
    assert "cpu" in block
    assert "keystroke" in block


def test_the_block_works_with_no_config_at_all():
    # The tray can be built without a Config; a feedback report must not need one.
    assert "Rekounts" in feedback.collect(None)


def test_a_config_that_raises_does_not_break_the_report():
    class Hostile:
        def get(self, key):
            raise RuntimeError("config on fire")

    assert "Rekounts" in feedback.collect(Hostile())


def test_the_block_never_carries_content(identity, config, monkeypatch, tmp_path):
    """The whole promise, in one assertion set.

    The transcript, the note and the dictionary entry are not merely absent
    because nothing put them there — they are planted in the places the app
    really keeps them first, so this fails if the collector ever grows a reader
    for one of them.
    """
    (tmp_path / "scratchpad.json").write_text(SCRATCHPAD, encoding="utf-8")
    (tmp_path / "history.db").write_text(TRANSCRIPT, encoding="utf-8")
    config.set("microphone", f"Microphone ({USERNAME}'s AirPods)")
    monkeypatch.setattr(feedback, "log_tail",
                        lambda *a, **k: f"{TRANSCRIPT}\n{DICTIONARY}")

    block = feedback.collect(config)

    for secret in (TRANSCRIPT, SCRATCHPAD, DICTIONARY, USERNAME, MACHINE, HOME):
        assert secret not in block


def test_the_microphone_name_is_not_collected(config):
    # Mic names routinely contain a person's name ("Ryan's AirPods").
    config.set("microphone", "Microphone (Somebody's AirPods)")
    assert "AirPods" not in feedback.collect(config)


def test_the_log_is_only_included_when_asked(config, monkeypatch):
    monkeypatch.setattr(feedback, "log_tail", lambda *a, **k: "a log line")
    assert "a log line" not in feedback.collect(config)
    assert "a log line" in feedback.collect(config, log_lines=10)


# ======================================================================= log
def _write_log(text):
    path = feedback.log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_missing_log_is_not_an_error():
    # APPDATA is a throwaway directory for the whole suite (tests/conftest.py).
    assert feedback.log_tail() == ""


def test_the_log_tail_is_scrubbed_and_capped(identity):
    _write_log("\n".join(
        [f"line {n}: reading {HOME}\\Rekounts\\config.json" for n in range(200)]))
    tail = feedback.log_tail(lines=12)
    assert HOME not in tail
    assert "%USERPROFILE%" in tail
    assert len(tail.splitlines()) == 12
    assert "line 199" in tail          # the END of the log, which is the news


def test_one_enormous_line_cannot_blow_the_cap():
    _write_log("x" * 50_000)
    assert len(feedback.log_tail()) <= feedback.LOG_TAIL_CHARS + 1


def test_an_undecodable_log_line_still_reports(identity):
    path = feedback.log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bad byte \xff here\nsecond line\n")
    assert "second line" in feedback.log_tail()


# ====================================================================== URLs
def test_the_issue_url_points_at_this_repos_new_issue_form():
    url = feedback.github_issue_url("App: Rekounts 0.4.0", SLUG)
    assert url.startswith(f"https://github.com/{SLUG}/issues/new?")
    assert "title=" in url and "body=" in url


def test_the_issue_url_carries_the_block_the_user_reviewed():
    url = feedback.github_issue_url("App%3A Rekounts 0.4.0 <marker>", SLUG)
    assert "%3Cmarker%3E" in url        # percent-encoded, not injected raw
    assert " " not in url


def test_the_issue_body_prompts_for_what_happened():
    url = feedback.github_issue_url("App: Rekounts", SLUG)
    assert "What%20happened" in url


def test_the_mailto_url_uses_the_one_support_address():
    url = feedback.mailto_url("App: Rekounts 0.4.0")
    assert url.startswith(f"mailto:{feedback.SUPPORT_EMAIL}?")
    assert "subject=" in url and "body=" in url


def test_the_mailto_body_uses_percent_escapes_not_plus_signs():
    # A "+" in a mailto body is shown literally by mail clients, not as a space.
    url = feedback.mailto_url("App: Rekounts")
    assert "+" not in url
    assert "%20" in url


def test_a_caller_can_point_the_email_somewhere_else():
    url = feedback.mailto_url("x", "someone@example.com")
    assert url.startswith("mailto:someone@example.com?")


def test_an_enormous_block_is_trimmed_to_fit_each_link():
    huge = "\n".join(f"line {n} of a very long diagnostic block" for n in range(5000))

    issue = feedback.github_issue_url(huge, SLUG)
    mail = feedback.mailto_url(huge)

    assert len(issue) <= feedback.MAX_ISSUE_URL
    assert len(mail) <= feedback.MAX_MAILTO_URL
    # Trimmed, not truncated: the fence the body opened is still closed, so the
    # issue renders as a code block instead of eating the rest of the page.
    assert issue.count("%60%60%60") == 2
    assert "trimmed" in issue and "trimmed" in mail


def test_a_report_with_no_diagnostics_is_still_a_valid_link():
    assert feedback.github_issue_url("", SLUG).startswith("https://github.com/")
    assert feedback.mailto_url("").startswith("mailto:")


def test_the_urls_scrub_even_if_handed_raw_text(identity):
    for url in (feedback.github_issue_url(f"home: {HOME}", SLUG),
                feedback.mailto_url(f"home: {HOME}")):
        assert "Ryank" not in url


def test_building_a_report_does_not_import_qt():
    """ARCHITECTURE.md: Qt must not load before the speech model.

    A diagnostics helper that reached for PySide6 to read its version would be
    a new way to break that, so it reads the version out of sys.modules and
    this test proves it — in a fresh interpreter, because the rest of the suite
    has Qt loaded already.
    """
    code = ("import sys; import rekounts.feedback as f; f.collect(None);"
            " assert 'PySide6' not in sys.modules, sorted(sys.modules)[:5]")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True)
    assert out.returncode == 0, out.stderr


# ============================================================== the dialog
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.ui.feedback_dialog import FeedbackDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def dialog(app, config):
    opened = []
    d = FeedbackDialog(config, opener=opened.append, slug=SLUG)
    d.opened = opened
    yield d
    d.deleteLater()


def test_the_dialog_shows_the_block_before_anything_moves(dialog, config):
    assert dialog.diagnostics() == feedback.collect(config)
    assert "Rekounts" in dialog.diagnostics()


def test_the_dialog_has_no_send_button(dialog):
    labels = [b.text().lower() for b in dialog.findChildren(QtWidgets.QPushButton)]
    assert not any("send" in text and "feedback" not in text for text in labels)
    assert any("copy" in text for text in labels)
    assert any("save" in text for text in labels)


def test_the_preview_is_read_only(dialog):
    assert dialog.view.isReadOnly()


def test_github_opens_a_prefilled_issue_and_posts_nothing(dialog):
    dialog.open_github()
    assert len(dialog.opened) == 1
    assert dialog.opened[0].startswith(f"https://github.com/{SLUG}/issues/new?")


def test_email_opens_a_prefilled_message(dialog):
    dialog.open_email()
    assert dialog.opened[0].startswith(f"mailto:{feedback.SUPPORT_EMAIL}?")


def test_both_links_carry_exactly_what_was_on_screen(dialog):
    from urllib.parse import unquote

    dialog.open_github()
    dialog.open_email()
    for url in dialog.opened:
        assert dialog.diagnostics() in unquote(url)


def test_copy_puts_the_block_on_the_clipboard(dialog, app):
    dialog.copy()
    assert app.clipboard().text() == dialog.diagnostics()


def test_save_writes_the_block_to_the_chosen_file(dialog, tmp_path):
    target = tmp_path / "diagnostics.txt"
    dialog.save(str(target))
    assert dialog.diagnostics() in target.read_text(encoding="utf-8")


def test_cancelling_the_save_dialog_writes_nothing(dialog, tmp_path):
    dialog.save("")            # what getSaveFileName returns on cancel
    assert list(tmp_path.glob("*.txt")) == []


def test_ticking_the_log_box_adds_scrubbed_log_lines(dialog, identity):
    _write_log(f"something went wrong in {HOME}\\Rekounts")
    dialog.include_log.setChecked(True)
    block = dialog.diagnostics()
    assert "something went wrong" in block
    assert HOME not in block


def test_the_log_box_is_off_until_the_user_ticks_it(dialog):
    assert dialog.include_log.isChecked() is False
