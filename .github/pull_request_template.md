<!-- One or two sentences: what does this change, and why? Link the issue if
     there is one. -->

## Checklist

- [ ] `python -m pytest` is green locally (CI also runs it on Windows, Linux
      and macOS)
- [ ] `ruff check .` is clean
- [ ] Docs updated if behavior changed — README / CHANGELOG / docs/…. This
      repo's docs describe what the code *actually does*; please keep it that
      way.
- [ ] If audio, hotkeys, insertion, the tray, the pill, the Hub or packaging
      changed: walked the relevant section of
      [docs/manual-smoke-test.md](../docs/manual-smoke-test.md)
- [ ] No network calls with user audio or text — privacy is the point

Licensing: contributions are accepted under the terms described in
[CONTRIBUTING.md](../CONTRIBUTING.md#contributions--licensing).
