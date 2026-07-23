> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# TalkativeAI — Overlay Upgrade Design

**Date:** 2026-07-14
**Status:** Approved design, ready for implementation
**Prereq:** builds on the live-preview overlay (shareable-milestone).

## Goal

Make the recording overlay (a) show **live level bars** that react to mic volume so the
user can see their mic is working, and (b) sit in a **fixed bottom-center** position on
the primary screen (Wispr Flow–style) instead of following the mouse cursor.

## Changes

### 1. Live level bars (VU meter)
- A row of ~12 vertical bars in the overlay that rise/fall with live mic amplitude,
  updating ~25×/sec. Flat when silent, tall/lively when speaking.
- Bars show a short rolling history: each tick shifts left, newest level on the right,
  so it reads as a moving meter rather than one jumping bar.
- **Data source:** `AudioRecorder.current_level()` returns the RMS amplitude of the most
  recent captured chunk (cheap; audio is already being captured). Display-only — does
  not affect transcription.
- A Qt timer in the overlay polls the level via a callback and repaints.

### 2. Fixed bottom-center position
- On show, overlay places itself horizontally centered and ~120px above the bottom of
  the **primary** screen's available area (above the taskbar). No longer reads the mouse.
- Multi-monitor: anchors to the primary screen (predictable). Following the active
  screen is deferred.

## What stays the same
- Live transcript preview text, auto-hide on release, final-text-typed-on-release.
- Only the overlay's position and visuals change.

## Architecture

- `AudioRecorder.current_level() -> float`: RMS of the last ~N frames of captured audio;
  returns 0.0 when not recording / no frames. Pure-ish (math over captured buffer),
  unit-testable via a helper that computes RMS of a supplied array.
- Overlay gains:
  - a `level_provider` callback (set by the entry point to `recorder.current_level`),
  - a `QTimer` (~40ms) that, while visible, reads the level, pushes it into a fixed-size
    history deque, and triggers a repaint,
  - a custom `paintEvent` that draws the bars from the history plus the label/preview text.
- Entry point wires `overlay.level_provider = recorder.current_level`. The timer only
  runs while the overlay is visible (started on show, stopped on hide).

## Error / edge behavior
- Level unreadable (between states) → treated as 0.0 → bars render flat. Never errors.
- Level provider missing → bars stay flat; no crash.

## Testing
- **Unit (TDD):** an `rms_level(audio)` helper — silence → ~0, louder array → higher,
  empty → 0.0. (The bar rendering and screen positioning are visual, verified manually.)
- **Regression:** existing 37 tests stay green.
- **Manual smoke:** hold hotkey → overlay appears bottom-center; bars jump when speaking,
  flat when silent; transcript preview still shows; hides on release.