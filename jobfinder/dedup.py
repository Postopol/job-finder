from __future__ import annotations

import re

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_DROP = {
    "remote", "удаленно",
    "senior", "junior", "middle", "lead", "sr", "jr", "mid", "intern", "principal", "staff",
    "сеньор", "джуниор", "джун", "мидл", "лид", "старший", "ведущий", "младший",
}


_TECH = [
    (re.compile(r"(?<!\w)c\+\+"), "cpp"),
    (re.compile(r"(?<!\w)c#"), "csharp"),
    (re.compile(r"\.net(?!\w)"), "dotnet"),
    (re.compile(r"node\.js"), "nodejs"),
]
_FULLTIME = re.compile(r"full[\s-]?time")


def _base(s: str) -> str:
    return s.lower().replace("ё", "е")


def dedup_key(company: str | None, title: str) -> str:
    t = _base(title)
    t = _BRACKETS.sub(" ", t)
    for rx, repl in _TECH:
        t = rx.sub(repl, t)
    t = _FULLTIME.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    words = [w for w in t.split() if w not in _DROP]
    c = " ".join(_base(company or "").split())
    return c + "|" + " ".join(words)


# Same key is not enough: «Middle Python Developer» and «Senior Python Developer», or
# «Data Scientist (RAG)» and «Data Scientist (Search)», are different vacancies.
_BRACKET_TEXT = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
_NOISE = _DROP | {"full", "time", "fulltime", "удаленка", "удаленная", "работа", "гибрид",
                  "hybrid", "office", "офис", "contract", "контракт", "fte", "b2b"}
_LOOKALIKE = str.maketrans("aceopxyk", "асеорхук")  # Latin letters that look Cyrillic


def _qualifier(title: str) -> str:
    """Bracket text without level/format words: «(Senior, Remote)» → «»."""
    parts = " ".join(a or b for a, b in _BRACKET_TEXT.findall(_base(title)))
    parts = _FULLTIME.sub(" ", parts)
    words = [w for w in _PUNCT.sub(" ", parts).split() if w not in _NOISE]
    return " ".join(words).translate(_LOOKALIKE)


def compatible(title_a: str, title_b: str) -> bool:
    """Titles with the same key may name one vacancy: levels and bracket qualifiers
    do not contradict (a side that has none agrees with anything)."""
    from .normalize import detect_seniority  # lazy: keeps this module light

    la, lb = detect_seniority(title_a or ""), detect_seniority(title_b or "")
    if la and lb and la != lb:
        return False
    qa, qb = _qualifier(title_a or ""), _qualifier(title_b or "")
    return not (qa and qb and qa != qb)
