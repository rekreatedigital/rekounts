# Speech model licenses and attribution

Rekounts does not train its own speech models. It redistributes, from its own
release host, the CTranslate2 conversions of OpenAI's Whisper models published by
SYSTRAN. Both the original weights and the conversions are MIT-licensed, which
permits redistribution provided the copyright notice and permission notice travel
with the files. This page is that notice, and a copy of it is uploaded as
`LICENSE-MODELS.txt` alongside the model assets in every release.

## What is redistributed

| Model name (in Settings) | Upstream repository | Conversion by |
| --- | --- | --- |
| `base` | [`Systran/faster-whisper-base`](https://huggingface.co/Systran/faster-whisper-base) | SYSTRAN |
| `small` | [`Systran/faster-whisper-small`](https://huggingface.co/Systran/faster-whisper-small) | SYSTRAN |
| `medium` | [`Systran/faster-whisper-medium`](https://huggingface.co/Systran/faster-whisper-medium) | SYSTRAN |

Each consists of four files — `config.json`, `model.bin`, `tokenizer.json` and
`vocabulary.txt` — redistributed **byte-for-byte unmodified**. The exact SHA256 of
every file is recorded in [`rekounts/models.py`](../rekounts/models.py) and
verified on the user's machine after download, so what you receive is provably
what upstream published.

The upstream repositories are the *provenance* of these files. The shipped app
never contacts `huggingface.co` — see [privacy.md](privacy.md).

## Whisper (original weights) — MIT

```
Copyright (c) 2022 OpenAI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## faster-whisper / CTranslate2 conversions — MIT

```
Copyright (c) 2023 SYSTRAN

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Adding a model

Model *selection* is a separate concern from delivery. To add one:

1. Add its entry to `MANIFEST` in `rekounts/models.py` (upstream repo, plus the
   size and SHA256 of each file — `scripts/publish_models.py <name> --hashes`
   prints the entry for you).
2. Add a row to the table above naming the upstream repo and its license. If the
   upstream is **not** MIT, its terms must be checked before it can be
   redistributed here — do not assume.
3. Run `python scripts/publish_models.py <name>` to upload the assets.
