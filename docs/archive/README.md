# Archive — historical documents

Everything under this folder is a **point-in-time design or plan kept for the
record**. It describes the project as it was imagined at the time of writing,
not as it is built today, and it is **not maintained**.

Known ways these documents have already drifted from reality (not exhaustive):

- They target a **CUDA GPU** and default to the `small` model; the shipped app
  runs on **CPU by default** with the `base` model.
- They describe the original two-hotkey scheme (`F8` hold, `Ctrl+Alt+Space`
  toggle); the shipped app uses a single `Ctrl+Win` hotkey with hold /
  double-tap / tap gestures.
- They predate the Hub, the instant-apply Settings page, and the monochrome
  pill redesign.
- Hardware specs, paths and machine notes refer to the original development
  machine, not to any requirement of the app.

For how the app actually works, read the [README](../../README.md),
[ARCHITECTURE.md](../../ARCHITECTURE.md) and [docs/privacy.md](../privacy.md).
