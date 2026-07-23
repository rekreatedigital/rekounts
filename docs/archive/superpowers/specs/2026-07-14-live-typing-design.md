> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# TalkativeAI — Live Chunk-Append Typing Design

**Date:** 2026-07-14
**Status:** Approved design, ready for implementation

## Goal

Type transcribed words into the focused app **as the user speaks** (phrase-by-phrase),
instead of only on release. Safe "chunk-append" approach: never delete or rewrite text
already typed in the document.

## Behavior

- While recording, every ~2s: transcribe audio-so-far, compute the **new tail** vs. what
  was already typed this session, type only the new words (keystrokes).
- On release: run the final full transcription and type only the remaining un-typed tail
  (guarantees the end of the sentence isn't dropped). Never rewrites earlier text.
- Overlay level bars remain as the mic indicator.

## The diff algorithm (heart of the feature)

`new_suffix(already_typed: str, new_transcript: str) -> str`:
- Normalize both to comparable token streams (whitespace-collapsed).
- Find the longest common prefix (by words) of `already_typed` and `new_transcript`.
- Return the remainder of `new_transcript` after that prefix (the words to type now).
- If `new_transcript` diverges from `already_typed` before its end, keep what was typed
  and return the portion after the divergence (accepting minor inaccuracy — the safe,
  no-delete tradeoff). If nothing new, return "".
- Leading space handling: caller prepends a space when `already_typed` is non-empty and
  the new suffix doesn't already start with one.

This function is pure and unit-tested.

## Architecture

- `AudioRecorder.snapshot()` (exists) supplies audio-so-far.
- **Streaming loop** (background thread), started on record-start, stopped on release:
  every ~2s → transcribe snapshot (fast path: `beam_size=1`, no VAD) → `new_suffix()`
  vs. running `typed` string → if non-empty, `TextInserter.insert()` the new words and
  append to `typed`.
- **Insertion:** streaming uses keystroke typing (not clipboard paste) so it doesn't
  clobber the clipboard each chunk. (The `TextInserter` "keystroke" path.)
- **On release:** the controller's final `_process` computes `new_suffix(typed, final)`
  and types only that tail, rather than the whole transcript.
- **Cleanup:** per-chunk light cleanup only (trim/spacing). Whole-sentence rules
  (capitalization, filler removal that would require rewriting earlier words) are not
  applied to streamed chunks — streamed text is closer to raw Whisper. This is the
  honest tradeoff of live typing.

## Config

- New toggle `live_typing` (default **True**). When False, behavior reverts to the
  current type-clean-text-on-release path.
- Exposed in Settings as a checkbox.

## Honest tradeoffs (documented)

- CPU: re-transcribing every 2s is heavier; on CPU words appear in ~2s bursts, not
  instantly per word.
- Accuracy: streamed text can keep an early mis-hear that a full-clip pass would have
  fixed; we never rewrite, so it stays. Acceptable per the safe design choice.

## Error handling

- Streaming transcription errors → caught/ignored (best-effort); the final release pass
  still runs.
- If `live_typing` is on but a chunk types nothing new, nothing happens (no-op).
- State machine unchanged: streaming runs only in RECORDING; final tail in PROCESSING.

## Testing

- **Unit (TDD):** `new_suffix()` — identical prefix → tail only; exact match → ""; empty
  already_typed → whole transcript; divergence → suffix-after-divergence; whitespace
  normalization.
- **Regression:** existing 40 tests stay green.
- **Manual smoke:** speak a long sentence → words appear in ~2s groups while speaking;
  on release the tail completes; no text is deleted; toggle off → type-on-release works.