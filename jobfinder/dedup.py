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
