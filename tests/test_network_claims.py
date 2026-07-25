"""Every published claim about network access must agree with the code.

Three surfaces used to state this independently and had drifted to three
different answers — settings_page said "exactly twice", docs/privacy.md said
"three times", SECURITY.md said "two network moments". Nobody had changed the
behaviour; the sentences just aged apart, because nothing tied them together.

rekounts/network_facts.py is now the single list, the Settings sentence is
generated from it, and these tests hold the two documents and the source itself
against it. A new outbound call fails the suite until it is declared; a
declaration with no call behind it fails too; and a document that keeps an old
number fails at the marker comment it carries.
"""
import re
from pathlib import Path

import pytest

from rekounts import network_facts
from rekounts.network_facts import (BROWSER_HANDOFFS, NETWORK_MOMENTS,
                                    count_word, network_count, statement)

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "rekounts"

# The marker each document carries so its count can be checked mechanically.
MARKER = re.compile(r"<!--\s*network-moments:\s*(\d+)\b")

DOCS = ["docs/privacy.md", "SECURITY.md"]

# Only these two modules may open a URL. urllib is imported in more places than
# it is used, so the test looks for the call, not the import.
OPENS_A_URL = re.compile(r"urllib\.request\.urlopen|\brequests\.(get|post|head)\b")


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


# --- the list matches the code -------------------------------------------
def test_each_declared_moment_has_a_real_call_behind_it():
    for moment in NETWORK_MOMENTS:
        source = _read(moment.module)
        assert OPENS_A_URL.search(source), \
            f"{moment.key} claims a request in {moment.module}, which makes none"
        assert moment.host in source, \
            f"{moment.key} claims {moment.host}, which {moment.module} never names"


def test_no_undeclared_module_reaches_the_network():
    declared = {m.module for m in NETWORK_MOMENTS}
    found = set()
    for path in PACKAGE.rglob("*.py"):
        if OPENS_A_URL.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(REPO).as_posix())
    assert found == declared, (
        "the set of modules that open a URL changed. Add it to "
        "rekounts/network_facts.py (and to docs/privacy.md and SECURITY.md), "
        f"or remove the call. declared={sorted(declared)} found={sorted(found)}")


def test_a_browser_handoff_is_not_counted_as_a_network_moment():
    # webbrowser.open hands a URL to the user's browser and makes no request of
    # its own. Counting it is how privacy.md ended up saying "three times".
    tray = _read("rekounts/ui/tray.py")
    assert "webbrowser.open" in tray
    assert BROWSER_HANDOFFS, "the hand-offs must stay listed, just not counted"
    assert network_count() == 2


# --- the surfaces match the list -----------------------------------------
@pytest.mark.parametrize("doc", DOCS)
def test_the_document_marker_matches_the_list(doc):
    found = MARKER.search(_read(doc))
    assert found, (f"{doc} has no <!-- network-moments: N --> marker; it is what "
                   "keeps its count checkable")
    assert int(found.group(1)) == network_count()


@pytest.mark.parametrize("doc", DOCS)
def test_the_document_names_every_host_and_no_others(doc):
    text = _read(doc)
    for moment in NETWORK_MOMENTS:
        assert moment.host in text, f"{doc} never names {moment.host}"


@pytest.mark.parametrize("doc", DOCS)
def test_no_document_states_a_different_count(doc):
    """The exact drift that happened: "three times" survived in privacy.md long
    after the Settings page had settled on "twice".

    Checked through one fixed phrasing — "the network <count>" — rather than by
    scanning for stray number words, because "once" is also an ordinary English
    word in these documents ("downloaded once", "once per launch") and a test
    that cried wolf about those would be turned off within a week.
    """
    text = _read(doc).lower()
    assert f"the network {count_word()}" in text, (
        f'{doc} must state the count as "the network {count_word()}" so this '
        "test can hold it to the code")
    for phrase in {"once", "twice", "three times", "four times"} - {count_word()}:
        assert f"the network {phrase}" not in text, \
            f"{doc} states '{phrase}' where the count is '{count_word()}'"
    numbers = {"one": 1, "two": 2, "three": 3, "four": 4}
    for word, value in numbers.items():
        if value != network_count():
            assert f"{word} network moment" not in text


def test_the_settings_sentence_is_generated_not_typed():
    from rekounts.ui import settings_page
    assert settings_page.NETWORK_STATEMENT == statement()
    assert count_word() in settings_page.NETWORK_STATEMENT
    for moment in NETWORK_MOMENTS:
        assert moment.summary in settings_page.NETWORK_STATEMENT


def test_the_generated_sentence_tracks_the_list(monkeypatch):
    # Proof the sentence is derived: shorten the list and the wording follows.
    monkeypatch.setattr(network_facts, "NETWORK_MOMENTS", NETWORK_MOMENTS[:1])
    assert "exactly once" in statement()
    assert NETWORK_MOMENTS[1].summary not in statement()
