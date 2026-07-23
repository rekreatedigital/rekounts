# Order matters: first entry is the default fallback.
LANGUAGES = [
    ("Auto-detect", "auto"),
    ("English", "en"),
    ("Tagalog", "tl"),
]


def labels() -> list[str]:
    return [label for label, _ in LANGUAGES]


def code_for_label(label: str) -> str:
    for l, code in LANGUAGES:
        if l == label:
            return code
    return LANGUAGES[0][1]


def label_for_code(code: str) -> str:
    for label, c in LANGUAGES:
        if c == code:
            return label
    return LANGUAGES[0][0]
