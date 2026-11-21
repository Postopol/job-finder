"""Halal filter: jobs in banned industries (gambling, alcohol, banks, ...) are not collected.

The lists live in halal.toml. See its header for where each list is matched.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .filters import _word_pattern
from .models import Job

RULES_FILE = Path(__file__).with_name("halal.toml")


@dataclass(frozen=True)
class Category:
    name: str
    label: str
    companies: re.Pattern | None
    words: re.Pattern | None
    phrases: re.Pattern | None


def _compile(items: list[str]) -> re.Pattern | None:
    if not items:  # an empty alternation would match everything
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(_word_pattern(w) for w in items) + r")(?!\w)",
                      re.IGNORECASE)


@lru_cache(maxsize=1)
def categories() -> tuple[Category, ...]:
    data = tomllib.loads(RULES_FILE.read_text(encoding="utf-8"))
    return tuple(Category(name, c.get("label", name), _compile(c.get("companies", [])),
                          _compile(c.get("words", [])), _compile(c.get("phrases", [])))
                 for name, c in data.items())


def labels() -> dict[str, str]:
    return {c.name: c.label for c in categories()}


def banned_reason(job: Job) -> str | None:
    """Name of the banned category the job belongs to, or None."""
    company = (job.company or "").replace("ё", "е").replace("Ё", "Е")
    head = f"{job.title or ''}\n{company}"
    full = f"{head}\n{job.description_text or ''}"
    for c in categories():
        if c.companies is not None and c.companies.search(company):
            return c.name
        if c.words is not None and c.words.search(head):
            return c.name
        if c.phrases is not None and c.phrases.search(full):
            return c.name
    return None
