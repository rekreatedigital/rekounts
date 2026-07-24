# Contributing to Rekounts

Thanks for wanting to help! Rekounts is a small, local-first dictation app, and
contributions are very welcome.

## The short version

- Open pull requests against
  [github.com/rekreatedigital/rekounts](https://github.com/rekreatedigital/rekounts).
- Rekounts is **GPL-3.0**, and contributions are accepted under a light
  CLA — see [Contributions & licensing](#contributions--licensing) below.
- **Keep the tests green.** Every PR must pass the suite:

  ```bat
  .venv\Scripts\python -m pytest
  ```

  CI runs the same tests on Windows for Python 3.11 and 3.12, on Linux and
  macOS for 3.12 (the app is Windows-only, but the suite fakes the Windows
  pieces — that keeps the code portable for a future macOS port), plus a
  `ruff check .` lint pass. All of it is quick to run locally:

  ```bat
  .venv\Scripts\python -m pip install -r requirements-test.txt
  .venv\Scripts\python -m pytest
  .venv\Scripts\python -m ruff check .
  ```

## Getting set up

1. Fork and clone the repo.
2. Double-click `setup.bat` (or follow the manual steps in the
   [README](README.md#install--from-source-developers)).
3. Run the app with `run.bat` and the tests with `pytest` (above).

Nothing else is needed to work on the app. Two extras are **build-time only**,
and only if you are producing a release:

| Tool | Install | Needed for |
| --- | --- | --- |
| [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3+ | `winget install -e --id JRSoftware.InnoSetup` | `Rekounts-Setup-<version>.exe`. `build.bat` finds it automatically, and skips the installer step with a note if it is absent. |
| [Pillow](https://python-pillow.org/) | `pip install pillow` | regenerating `assets/icon.ico` with `tools/make_icon.py`. The `.ico` is committed, so you only need this if you are changing the icon. |

## Good to know

- **Add a test for new logic.** Pure-logic code (config, text cleaning, state
  machine, controller, startup, …) is unit-tested and fast — please keep it that
  way. Hardware/UI changes should also be walked through
  [docs/manual-smoke-test.md](docs/manual-smoke-test.md).
- **Read [ARCHITECTURE.md](ARCHITECTURE.md) first** — especially the note about
  *not* importing Qt before the Whisper model loads. Getting that wrong
  hard-crashes the app.
- **Privacy is the point.** The app must not make network calls with user audio or
  text. Keep everything local.
- Use clear commit messages ([Conventional Commits](https://www.conventionalcommits.org/)
  are appreciated but not required).

## Contributions & licensing

The app ships under **GPL-3.0** ([LICENSE](LICENSE)) and always will be
available under it. Contributions are accepted under a **Contributor License
Agreement (CLA)**: you keep the copyright to your work and license it to the
project under GPL-3.0, and you additionally grant **Rekreate Digital** the
right to relicense or dual-license the combined work. That grant is what makes
it possible to, say, offer the app under another license someday without
having to track down every past contributor.

CLA signing will be handled automatically on your first pull request (via
cla-assistant) once that bot is set up; until then, opening a pull request
records your agreement to the terms above. If you're not comfortable with the
CLA, please open an issue instead of a PR — bug reports and ideas need no
paperwork.

The project's name and logo are not covered by the GPL — see
[TRADEMARKS.md](TRADEMARKS.md).

## Reporting bugs / ideas

Open an issue — there are templates for bug reports (what happened, your
Windows/Python versions, a log excerpt) and feature requests. For anything you
believe is a security problem, use private reporting instead: see
[SECURITY.md](SECURITY.md).
