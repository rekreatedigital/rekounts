# Security policy

Rekounts is a local Windows app. There is no server component, no account
system and no telemetry — your audio and text stay on the machine. The attack
surface is the app itself plus its two network moments: the one-time speech-model
download from **this project's own GitHub release host** (never Hugging Face —
see [docs/privacy.md](docs/privacy.md)), and the read-only GitHub API call behind
**Check for Updates**. Both are triggered by you, with one opt-in exception:
**Settings → System → Check for updates automatically** (off by default) makes
that same read-only API call once per launch.

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
