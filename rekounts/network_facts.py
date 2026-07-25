"""The one place that says how often Rekounts touches the network.

This exists because three published statements drifted apart. The Settings page
said "exactly twice", docs/privacy.md said "three times", and SECURITY.md said
"two network moments" — three numbers, three files, each edited on its own. For
an app whose entire pitch is that nothing leaves your machine, the count being
approximate is the worst possible detail to get wrong.

So the count is derived here from a list of the actual call sites, the Settings
page renders its sentence from that list, and tests/test_network_claims.py
checks three things on every run:

  * every moment listed here has a real ``urlopen`` behind it, in the module it
    names;
  * no OTHER module in the package opens a URL — a new one fails the suite
    until it is either removed or declared here;
  * the two documents agree with this list, by count and by host.

The disagreement was also substantive, not just arithmetic. Rekounts makes two
requests. The third thing privacy.md was counting — Help, and clicking an
update notification — hands a URL to your web browser and makes no request of
its own, which is a genuinely different promise and is listed separately below.
Keep it that way: a browser hand-off is not a network moment for this app, and
collapsing the two categories is how the count drifted in the first place.

Nothing here is a setting and nothing here is read at runtime except the
sentence. It is documentation that the test suite can check.
"""

from typing import NamedTuple


class NetworkMoment(NamedTuple):
    """One place where Rekounts itself opens a connection."""

    key: str
    module: str          # the module holding the urlopen, for the test to find
    host: str            # the only host this moment can reach
    summary: str         # how the Settings sentence refers to it
    trigger: str         # what has to happen for it to fire at all


NETWORK_MOMENTS = (
    NetworkMoment(
        key="model-download",
        module="rekounts/models.py",
        host="github.com",
        summary="once to download the speech model the first time you use it",
        trigger="Once per model, on first use. Never again — later loads open a "
                "local directory and cannot reach the network at all.",
    ),
    NetworkMoment(
        key="update-check",
        module="rekounts/ui/tray.py",
        host="api.github.com",
        summary="when you check for updates — from the tray menu, or once per "
                "launch if you switch that on",
        trigger="Tray menu → Check for Updates. Also once per launch if you turn "
                "on Settings → System → Check for updates automatically, which "
                "is off until you do.",
    ),
)

# Not network moments: your browser makes these requests, not Rekounts. Listed
# so the difference stays deliberate rather than looking like an omission.
BROWSER_HANDOFFS = (
    "Tray menu → Help opens this project's README in your browser.",
    "Clicking an update notification opens the release page in your browser.",
)

_COUNT_WORDS = {1: "once", 2: "twice", 3: "three times", 4: "four times"}


def network_count() -> int:
    return len(NETWORK_MOMENTS)


def count_word() -> str:
    """"twice" — the phrase every surface uses for the same number."""
    return _COUNT_WORDS[network_count()]


def statement() -> str:
    """The sentence shown under Settings → Data & Privacy.

    Built from the list rather than typed out, so the number and the moments it
    counts cannot disagree with each other.
    """
    moments = list(NETWORK_MOMENTS)
    joined = ", ".join(m.summary for m in moments[:-1])
    if joined:
        joined = f"{joined}, and {moments[-1].summary}"
    else:
        joined = moments[-1].summary
    return ("Rekounts runs entirely on this machine. It reaches the network "
            f"exactly {count_word()}: {joined}. Your audio and your text never "
            "leave this computer.")
