"""Name matching across documents (VERIFICATION.md "Name matching"). Marathi/Hindi names are
transliterated, then both sides are folded to a rough phonetic key, so "आरव सुनील पाटील",
"PATIL AARAV SUNIL" and "Aarav S. Patil" all match."""

import re
import unicodedata
from typing import Literal

from indic_transliteration import sanscript
from rapidfuzz import fuzz

Band = Literal["match", "minor_variation", "mismatch"]
MATCH, MINOR = 92.0, 80.0

HONORIFICS = {
    "shri",
    "shree",
    "sri",
    "smt",
    "kumari",
    "kum",
    "ku",
    "mr",
    "mrs",
    "ms",
    "miss",
    "sau",
}
# Order matters: "chh" before "ch"-free folds, digraphs before the double-letter squeeze.
FOLDS = (
    ("chh", "ch"),
    ("aa", "a"),
    ("ee", "i"),
    ("oo", "u"),
    ("ph", "f"),
    ("sh", "s"),
    ("th", "t"),
    ("dh", "d"),
    ("kh", "k"),
    ("gh", "g"),
    ("bh", "b"),
    ("w", "v"),
    ("z", "j"),
)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _latin(name: str) -> str:
    """Devanagari -> ITRANS, minus the inherent final 'a' ("Arava" -> "Arav"). ITRANS writes long
    vowels in capitals, so a final long A ("सुनीता" -> "sunItA") is kept."""
    if not _DEVANAGARI.search(name):
        return name
    itrans = sanscript.transliterate(name, sanscript.DEVANAGARI, sanscript.ITRANS)
    itrans = itrans.replace(".N", "n").replace("M", "n").replace("H", "")
    return re.sub(r"(?<=[^aeiouAEIOU\s])a\b", "", itrans)


def tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKC", _latin(name)).casefold()
    s = re.sub(r"[^a-z\s]", " ", s)
    out = []
    for t in s.split():
        if t in HONORIFICS:
            continue
        for a, b in FOLDS:
            t = t.replace(a, b)
        out.append(re.sub(r"(.)\1+", r"\1", t))
    return out


def _expand_initials(a: list[str], b: list[str]) -> list[str]:
    """'r' -> the first unused token of the other name that starts with r."""
    pool = [t for t in b if len(t) > 1]
    out = []
    for t in a:
        hit = next((p for p in pool if len(t) == 1 and p.startswith(t)), None)
        if hit:
            pool.remove(hit)
        out.append(hit or t)
    return out


def score(a: str, b: str) -> float:
    """0-100, order-insensitive. A name with extra tokens (middle/father's name) still matches.
    token_set_ratio alone dilutes one wrong token in a long name (Patil/Patel scored 94, Sharma/
    Verma 82), so the weakest token of the shorter name caps the score.
    ponytail: no Jaro-Winkler tie-break; add it if two candidates ever need ranking."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    ta, tb = _expand_initials(ta, tb), _expand_initials(tb, ta)
    short, other = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    weakest = min(max(fuzz.ratio(t, o) for o in other) for t in short)
    return round(min(fuzz.token_set_ratio(" ".join(ta), " ".join(tb)), weakest), 1)


def band(s: float) -> Band:
    return "match" if s >= MATCH else "minor_variation" if s >= MINOR else "mismatch"


def compare(a: str, b: str) -> tuple[float, Band]:
    s = score(a, b)
    return s, band(s)


def in_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text))


def same_name_in_english(name: str, other: str) -> bool:
    """other is name written in English letters: every word matches and none is missing
    ("KARTIK DILIP KOKATE" for "कार्तिक दिलीप कोकाटे"; not "Kartik Kokate")."""
    return (
        in_devanagari(name)
        and not in_devanagari(other)
        and len(tokens(name)) == len(tokens(other))
        and band(score(name, other)) == "match"
    )


def normalized(name: str) -> str:
    return " ".join(sorted(tokens(name)))
