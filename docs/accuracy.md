# Getting the best accuracy

How to pick a speech model, measure the difference on your own voice, and what
a GPU does or doesn't buy you. Moved out of the README so the front page stays
about getting started — everything here is for when you want to tune.

## Accuracy guide

Accuracy comes from two things you can change here: the **model** (the engine)
and, if you have one, a **GPU**. This is deliberately a *local* app — no cloud,
no account — so it can't match a huge server model, but a good local setup gets
close for everyday dictation.

**Picking a model.** Bigger models mishear fewer words, especially on accents,
names and fast or mumbled speech — but they're much slower on a CPU. Processing
time below is a fraction of the clip length — so 0.20× means a 10-second
dictation is ready in ~2 seconds. Measured on a fast CPU (AMD Ryzen 7 7800X3D,
int8); **older machines will be proportionally slower**, so the ranking matters
more than the absolute numbers:

| Model | Relative speed (CPU) | Good for |
| --- | --- | --- |
| `base` | ~0.09× (fastest) | old/weak machines, quick notes |
| `small` | ~0.20× (**default**) | the everyday sweet spot on CPU |
| `medium` | ~0.6–0.7× | more accuracy when you'll wait a beat |
| `distil-large-v3` | ~0.8× CPU | near top accuracy, better on a GPU |
| `large-v3-turbo` | ~0.8× CPU | best accuracy — really wants a GPU |

On CPU, `medium` and the large models take several seconds per dictation; they
shine on a GPU. `small` is the default because it's a clear accuracy step up
from `base` while still feeling instant on CPU.

> **Measure it on your own voice.** Whisper's own numbers rank the models, but
> the only ranking that matters is on *your* accent and *your* mic. `tools/
> asr_bench.py` does exactly that: record ~10 short clips, write down what you
> said, and it reports word error rate and speed per model. Nothing you record
> leaves your machine or enters git. See the header of that file for the steps.

**Using a GPU (optional) — this is the big win.** An NVIDIA GPU doesn't just
make the big models usable, it makes them *faster than `small` on CPU*. Measured
on an RTX 5070 Ti (16 GB, `int8_float16`), same clips as above:

| Model | GPU | CPU | Speed-up |
| --- | --- | --- | --- |
| `small` | ~0.06× | ~0.20× | ~3.5× |
| `medium` | ~0.08× | ~0.6–0.7× | ~7× |
| `distil-large-v3` | ~0.04× | ~0.73× | ~18× |
| `large-v3-turbo` | ~0.04× | ~0.72× | ~16× |

(Figures vary ~10–15% run to run depending on GPU clocks; the ranking is stable.)

Note the shape of that table: on a GPU, **`large-v3-turbo` is both the most
accurate option and among the fastest** (turbo and distil have far fewer decoder
layers than `large-v3`). So if you have a working NVIDIA GPU, there's little
reason not to run `large-v3-turbo`.

> **Availability note:** the in-app Model list currently offers `base`, `small`
> and `medium`. The two large models are benchmarked here but not yet published
> to the app's release host — they'll appear in the dropdown the moment they
> are. Until then `tools/asr_bench.py` can still run them for measurement.

To turn it on, set **Processing → Auto** in Settings. Auto probes whether the
GPU can *actually transcribe* — not just load a model, since a missing CUDA
library only fails on the first real use — and silently falls back to CPU if it
can't, so it's always safe to leave on.

**This needs a from-source install.** The packaged `.exe` deliberately excludes
the whole CUDA stack (`Rekounts.spec`), so there is no GPU for Auto to find in
it — which is why the **Processing** row is not shown in the installed app at
all, rather than offering a switch that always lands on CPU.

GPU needs the CUDA runtime libraries installed in the same environment. All
three of these are required (cuBLAS depends on cudart, so leaving it out gives a
confusing `cublas64_12.dll is not found`):

```
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12
```

Without them, Auto simply stays on CPU — they are **not** a required dependency
of the app. Verified working on an RTX 50-series (Blackwell, `sm_120`) card with
ctranslate2 4.8.1 and a CUDA 13 driver; the CUDA-12 wheels are correct even on a
CUDA-13 driver. Power users can force `"device": "cuda"` in `config.json`, but
`Auto` is the safe choice.

**Mic matters as much as the model.** The model only ever hears what your mic
captures. A close, clean mic beats a distant laptop mic more than one model size
does. Use Settings → **Test** to confirm "Heard you clearly". Heavy virtual-mic
processing (noise suppression, "AI" voice effects) can smear the audio the model
sees — if accuracy is poor, try your plain hardware mic.

**What the Dictionary is (and isn't).** The Dictionary in the Hub is
*personalization*, not the accuracy engine. It biases recognition toward names
and jargon you add (your app's product names, colleagues' names, acronyms) so
the model spells them your way. It won't fix general mishearing — that's the
model's job. Use it for the handful of words it keeps getting wrong.

**Coming later.** A local AI cleanup pass (grammar/punctuation polish, all
on-device) is planned to close more of the gap to cloud tools — separate from
this raw-accuracy work.

## CPU vs GPU

Transcription runs on **CPU by default**, which is fast enough for dictation
with the `small` model on a modern machine. To use an NVIDIA GPU, run from
source and set **Processing → Auto** in Settings (or `"device": "auto"` in
`config.json`) — see the **Accuracy guide** above for what the GPU needs and how
the safe fallback works.

**The Processing row is shown only where the choice can do something:** a
from-source run on Windows or Linux. The installed app is a CPU-only build, and
on a Mac the speech engine (CTranslate2) has only a CUDA backend, so `auto`
finds nothing to use and runs on the CPU. In both cases the row is absent
rather than present-and-inert. `"device"` in `config.json` is still read and
still obeyed everywhere, so a config file moves between the two without
surprises.
