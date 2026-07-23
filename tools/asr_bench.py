"""ASR accuracy + latency benchmark for Rekounts's model/decode choices.

WHY THIS EXISTS
---------------
Rekounts's transcription quality on accented, natural speech is the product
of two things we can actually change locally: the *model* (base/small/medium/
distil-large-v3/large-v3-turbo) and the *decode parameters* (beam size, VAD,
language pinning, temperature). Every claim in a PR that touches those knobs
must be backed by numbers, not vibes. This harness produces those numbers:
word error rate (WER) for accuracy and real-time factor (RTF) for latency,
over a LOCAL folder of your own recordings.

NO AUDIO IS COMMITTED TO THE REPO. Privacy-first means your voice never leaves
your machine, and it certainly never lands in git history. You record a small
sample set once, point this script at the folder, and read the table.

HOW TO BUILD A SAMPLE SET (~10 clips, 5-15 s each)
--------------------------------------------------
Put matching pairs in one folder — audio + reference transcript:

    my_clips/
        01_normal.wav      01_normal.txt
        02_fast.wav        02_fast.txt
        03_fillers.wav     03_fillers.txt
        04_technical.wav   04_technical.txt
        ...

* The .txt holds exactly what you said, written the way you'd want it typed
  (normal capitalisation and punctuation — WER scoring normalises both away).
* Cover the speech you actually dictate: a plain sentence, fast speech, one
  full of "um/uh/like" fillers, technical vocab and names, numbers/dates, and
  — if you code-switch — a Tagalog/English mix. Record on the SAME microphone
  you dictate with (mic pre-processing changes the audio the model sees).
* Audio can be .wav/.mp3/.m4a/.flac — anything ffmpeg reads; it's resampled to
  16 kHz mono automatically.

RUN IT
------
    .venv\\Scripts\\python.exe tools\\asr_bench.py --data my_clips

    # sweep specific models
    .venv\\Scripts\\python.exe tools\\asr_bench.py --data my_clips ^
        --models base small medium distil-large-v3

    # sweep a decode parameter (default language pin is en; try auto)
    .venv\\Scripts\\python.exe tools\\asr_bench.py --data my_clips ^
        --models small --language auto --beam 1 5

    # try the GPU (falls back to CPU with a note if CUDA can't load)
    .venv\\Scripts\\python.exe tools\\asr_bench.py --data my_clips --device cuda

Output is a table: per-config mean WER, median/mean RTF, and total wall time.
Lower WER = more accurate; RTF < 1.0 means faster than real time.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Heavy ML imports (faster_whisper, numpy) are deferred into the functions that
# need them so the pure scoring helpers below stay importable — and unit
# testable — on a machine without the model stack installed.

AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".webm")

# Matches Whisper's own text normaliser closely enough for dictation WER: drop
# everything that isn't a word character or space, so "Tuesday." == "tuesday"
# and "e-mail" == "email" don't get counted as errors of spelling we don't care
# about. Case is folded separately.
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — the canonical form
    both reference and hypothesis are reduced to before word-level scoring."""
    text = (text or "").lower()
    text = _NON_WORD.sub(" ", text)
    return _WS.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    norm = normalize_text(text)
    return norm.split() if norm else []


def _levenshtein(ref: list[str], hyp: list[str]) -> int:
    """Word-level edit distance (substitutions + insertions + deletions).

    Classic two-row dynamic program: O(len(ref) * len(hyp)) time, O(len(hyp))
    space. Operates on token lists, not characters, so the cost is the number
    of word edits — exactly the numerator of WER.
    """
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            cur.append(min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + cost  # substitution / match
            ))
        prev = cur
    return prev[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = (edits to turn hyp into ref) / (words in ref).

    Returns 0.0 when the reference is empty and the hypothesis is too, else 1.0
    for a non-empty hypothesis against an empty reference (everything is an
    insertion error). A perfect transcription scores 0.0; scoring can exceed
    1.0 when the hypothesis is much longer than the reference (many insertions),
    which is intentional — it's a real signal that the model is hallucinating.
    """
    ref_tokens = tokenize(reference)
    hyp_tokens = tokenize(hypothesis)
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    return _levenshtein(ref_tokens, hyp_tokens) / len(ref_tokens)


@dataclass
class Clip:
    name: str
    audio_path: Path
    reference: str


def load_dataset(folder: Path) -> list[Clip]:
    """Pair each audio file with its sibling .txt reference transcript.

    A clip with no matching .txt is skipped with a warning to stderr rather than
    guessed at — an unlabelled clip can't be scored. Returns clips sorted by name
    so runs are reproducible.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise SystemExit(f"--data folder not found: {folder}")
    clips: list[Clip] = []
    for audio in sorted(folder.iterdir()):
        if audio.suffix.lower() not in AUDIO_EXTS:
            continue
        ref = audio.with_suffix(".txt")
        if not ref.exists():
            print(f"  ! skipping {audio.name}: no {ref.name} reference",
                  file=sys.stderr)
            continue
        clips.append(Clip(audio.stem, audio,
                          ref.read_text(encoding="utf-8-sig").strip()))
    if not clips:
        raise SystemExit(
            f"no <audio>+<name>.txt pairs found in {folder} — see the module "
            "docstring for the expected layout.")
    return clips


@dataclass
class Config:
    """One decode configuration to benchmark."""
    model: str
    device: str = "cpu"
    beam_size: int = 5
    language: str | None = "en"   # None = auto-detect
    vad: bool = True
    temperature: float = 0.0

    def label(self) -> str:
        lang = self.language or "auto"
        vad = "vad" if self.vad else "novad"
        return (f"{self.model}/{self.device}/beam{self.beam_size}/"
                f"{lang}/{vad}")


@dataclass
class Result:
    config_label: str
    mean_wer: float
    per_clip_wer: dict[str, float]
    median_rtf: float
    mean_rtf: float
    total_audio_s: float
    total_proc_s: float
    device_used: str
    note: str = ""


def _resolve_model_id(model: str) -> str:
    """Map a friendly model name to what faster-whisper can actually load.

    Kept in sync with rekounts.transcriber.resolve_model_id so the bench
    measures the same thing the app runs. Imported lazily; falls back to the
    identity mapping if the app package isn't importable.
    """
    try:
        from rekounts.transcriber import resolve_model_id
        return resolve_model_id(model)
    except Exception:
        return model


def _build_model(cfg: Config):
    """Load a WhisperModel for cfg, honouring the CPU-fallback contract.

    Returns (model, device_used, note). A requested CUDA load that can't
    initialise falls back to CPU with a note, exactly like the app does, so the
    bench never dies on a machine without a working GPU.
    """
    import numpy as np
    from faster_whisper import WhisperModel
    model_id = _resolve_model_id(cfg.model)
    if cfg.device == "cuda":
        try:
            m = WhisperModel(model_id, device="cuda",
                             compute_type="int8_float16")
            # Loading isn't enough: a missing cuBLAS/cuDNN only bites on the
            # first encode. Validate with one tiny inference so a broken GPU
            # falls back here instead of crashing the whole sweep mid-run.
            list(m.transcribe(np.zeros(16000, dtype="float32"), beam_size=1)[0])
            return m, "cuda", ""
        except Exception as e:  # noqa: BLE001 - want the broadest fallback
            note = f"CUDA unusable ({type(e).__name__}); fell back to CPU"
            return (WhisperModel(model_id, device="cpu", compute_type="int8"),
                    "cpu", note)
    return WhisperModel(model_id, device="cpu", compute_type="int8"), "cpu", ""


def run_config(cfg: Config, clips: list[Clip], warmup: bool = True) -> Result:
    """Transcribe every clip under one config and score it.

    Latency is measured on a WARM model (one throwaway pass first) so the
    reported RTF reflects steady-state dictation, not the one-off kernel
    warm-up the app hides behind a startup thread.
    """
    import numpy as np
    from faster_whisper import decode_audio

    model, device_used, note = _build_model(cfg)

    if warmup:
        model.transcribe(np.zeros(16000, dtype="float32"), beam_size=1)

    per_clip_wer: dict[str, float] = {}
    rtfs: list[float] = []
    total_audio = 0.0
    total_proc = 0.0
    vad_params = dict(threshold=0.3, min_silence_duration_ms=500)

    for clip in clips:
        audio = decode_audio(str(clip.audio_path), sampling_rate=16000)
        duration = len(audio) / 16000.0
        t0 = time.perf_counter()
        segments, _ = model.transcribe(
            audio,
            language=cfg.language,
            beam_size=cfg.beam_size,
            temperature=cfg.temperature,
            condition_on_previous_text=False,
            vad_filter=cfg.vad,
            vad_parameters=vad_params if cfg.vad else None,
        )
        hyp = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.perf_counter() - t0

        wer = word_error_rate(clip.reference, hyp)
        per_clip_wer[clip.name] = wer
        rtfs.append(elapsed / duration if duration else 0.0)
        total_audio += duration
        total_proc += elapsed

    mean_wer = sum(per_clip_wer.values()) / len(per_clip_wer)
    return Result(
        config_label=cfg.label(),
        mean_wer=mean_wer,
        per_clip_wer=per_clip_wer,
        median_rtf=_median(rtfs),
        mean_rtf=sum(rtfs) / len(rtfs) if rtfs else 0.0,
        total_audio_s=total_audio,
        total_proc_s=total_proc,
        device_used=device_used,
        note=note,
    )


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def format_report(results: list[Result], clips: list[Clip]) -> str:
    """Human-readable table: one row per config, WER% and RTF side by side."""
    lines = []
    header = f"{'config':<38} {'WER%':>7} {'RTF(med)':>9} {'RTF(mean)':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in sorted(results, key=lambda x: x.mean_wer):
        lines.append(
            f"{r.config_label:<38} {r.mean_wer * 100:>6.1f} "
            f"{r.median_rtf:>9.3f} {r.mean_rtf:>10.3f}"
            + (f"   [{r.note}]" if r.note else ""))
    lines.append("")
    lines.append(f"{len(clips)} clips, "
                 f"{sum(c and 1 for c in clips)} scored. "
                 "Lower WER = more accurate; RTF<1.0 = faster than real time.")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Benchmark Rekounts model/decode choices (WER + RTF).")
    p.add_argument("--data", required=True,
                   help="folder of <audio>+<name>.txt reference pairs")
    p.add_argument("--models", nargs="+",
                   default=["base", "small", "medium"],
                   help="model names to sweep")
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                   help="cpu (default) or cuda (falls back to cpu on failure)")
    p.add_argument("--beam", nargs="+", type=int, default=[5],
                   help="beam size(s) to sweep")
    p.add_argument("--language", nargs="+", default=["en"],
                   help="language pin(s); 'auto' to detect")
    p.add_argument("--no-vad", action="store_true",
                   help="disable the VAD filter for the sweep")
    p.add_argument("--temperature", type=float, default=0.0)
    return p.parse_args(argv)


def configs_from_args(args: argparse.Namespace) -> list[Config]:
    configs = []
    for model in args.models:
        for beam in args.beam:
            for lang in args.language:
                configs.append(Config(
                    model=model,
                    device=args.device,
                    beam_size=beam,
                    language=None if lang == "auto" else lang,
                    vad=not args.no_vad,
                    temperature=args.temperature,
                ))
    return configs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    clips = load_dataset(Path(args.data))
    configs = configs_from_args(args)
    print(f"Loaded {len(clips)} clips; running {len(configs)} config(s).\n")

    results = []
    for cfg in configs:
        print(f"  running {cfg.label()} ...", flush=True)
        t0 = time.perf_counter()
        results.append(run_config(cfg, clips))
        print(f"    done in {time.perf_counter() - t0:.1f}s", flush=True)

    print()
    print(format_report(results, clips))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
