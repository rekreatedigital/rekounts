# Security policy

Rekounts is a local desktop app (Windows today; a macOS port is code-complete
pending hardware verification). There is no server component, no account
system and no telemetry — your audio and text stay on the machine.

<!-- network-moments: 2 (source of truth: rekounts/network_facts.py — keep this
     marker, tests/test_network_claims.py checks the number against the code) -->

The attack surface is the app itself plus the network twice: the one-time
speech-model download from **this project's own GitHub release host**
`github.com` (never Hugging Face — see [docs/privacy.md](docs/privacy.md)), and
the read-only `api.github.com` call behind **Check for Updates**. Both are
triggered by you, with one opt-in exception: **Settings → System → Check for
updates automatically** (off by default) makes that same read-only API call
once per launch.

Opening a page in your web browser — **Help**, clicking an update
notification, or **Send Feedback…** — is not counted here: the request is your
browser's (or your mail client's), and Rekounts makes none of its own. Feedback
carries a diagnostics block the app shows you first — versions and settings
only, with paths, user name and machine name scrubbed out — and it is composed
unsent, so nothing leaves until you send it yourself.
[docs/privacy.md](docs/privacy.md) lists every moment one by one.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: **Security → Report a
vulnerability** on this repository
([direct link](https://github.com/rekreatedigital/rekounts/security/advisories/new)).
Please don't open a public issue for anything you believe is exploitable.

You can expect an acknowledgement within a week. There is no bug bounty — this
is free software built in free time — but reports are taken seriously and
fixes credit the reporter (unless you'd rather stay anonymous).

## What's in scope

Anything that breaks the app's core promise, for example:

- a way to make the app transmit audio, transcripts, history or settings
  anywhere
- code execution via anything the app parses: `config.json`, `history.db`,
  the update-check response, clipboard contents, dictionary/hotword entries
- abuse of the launch-at-login registry write, the single-instance mutex, or
  the packaged `.exe`

Not in scope: other processes in the *same* Windows user session reading the
app's files — `history.db` and `config.json` are deliberately plain,
unencrypted files, and this is documented in [docs/privacy.md](docs/privacy.md).

## Supported versions

The latest release and `master`. There are no security backports to older
versions.
