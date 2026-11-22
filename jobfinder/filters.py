from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import CIS, Job

RESTRICTED = ["us only", "usa only", "u.s. only", "must be based in the us",
              "must reside in", "eu only", "europe only", "uk only",
              "только рф", "гражданство рф", "только россия",
              "only candidates from"]
WORLDWIDE = ["worldwide", "anywhere", "work from anywhere", "global",
             "весь мир", "любой стране", "любая страна"]
CIS_PHRASES = ["снг", "cis", "казахстан", "kazakhstan", "из любой точки снг"]

# "Hybrid Cloud Engineer", "hybrid mobile apps" are tech terms, not a work format
HYBRID_RE = re.compile(r"(?<!\w)(?:hybrid|гибрид\w*)(?!\w)(?!\s+(?:cloud|mobile|apps?|облак\w*)(?!\w))",
                       re.IGNORECASE)
# "3 days in office", "2 days a week in the office": a hybrid schedule
OFFICE_DAYS_RE = re.compile(r"(?<!\w)\d\s*days?\b[\w\s/]{0,12}?\bin(?:\s+the)?\s+office(?!\w)", re.IGNORECASE)
OFFICE_RE = re.compile(r"(?<!\w)(?:on-site|onsite|офис\w*)(?!\w)", re.IGNORECASE)
REMOTE_RE = re.compile(r"(?<!\w)(?:remote|удал[её]н\w*)(?!\w)", re.IGNORECASE)

# Regions that never include Kazakhstan: "Remote (Europe)", "LATAM" are not open to KZ.
# EMEA, Asia, CIS are left out on purpose: they may include KZ.
REGIONS_WITHOUT_KZ = {
    "europe", "eu", "european union", "western europe", "eastern europe", "central europe",
    "nordics", "scandinavia", "dach", "benelux", "latam", "latin america", "north america",
    "south america", "americas", "apac", "asia pacific", "oceania", "africa", "middle east", "mena",
}
_LOC_NOISE = re.compile(r"\b(?:remote(?:ly)?|only|based|residents?|citizens?|citizenship|"
                        r"candidates?|the|in|from)\b")


@dataclass
class FilterConfig:
    country: str = "KZ"
    stopwords: list[str] = field(default_factory=list)


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


def _any(text: str, phrases: list[str]) -> bool:
    return any(_has(text, p) for p in phrases)


def classify_scope(job: Job, country: str = "KZ") -> tuple[str, list[str]]:
    """(remote_scope, countries). A country list is «СНГ» only when it is all CIS and
    includes the user's `country`: «Russia only» is not available from Kazakhstan."""
    if job.countries:
        cis = country in job.countries and all(c in CIS for c in job.countries)
        return ("cis" if cis else "countries"), list(job.countries)
    if job.remote_scope not in ("unknown", "countries"):
        return job.remote_scope, []

    loc = job.location_raw or ""
    desc = job.description_text or ""
    full = f"{job.title} {loc} {desc}"

    if _any(f"{loc} {desc[:400]}", RESTRICTED):
        return "restricted", []
    if _region_limited(loc, country):
        return "restricted", []
    if _any(full, WORLDWIDE):
        return "worldwide", []
    if _any(full, CIS_PHRASES):
        return "cis", []
    if _any(full, RESTRICTED):
        return "restricted", []
    return "unknown", []


def _region_limited(loc: str, country: str) -> bool:
    """True when the location names only countries/regions and none of them is `country`:
    "REMOTE (US)", "Remote - Europe", "Europe, LATAM, the U.S." -> True; "Remote", "Москва",
    "Remote (EMEA)", "US + many countries" -> False (anything unrecognised means unsure)."""
    from .sources.geo import country_code  # lazy: jobfinder.sources imports this module

    text = re.sub(r"[()\[\]√+&]", ",", loc.lower())
    parts = re.split(r"[,;/|]|\band\b|\bor\b|\s-\s", text)
    tokens = [t for t in (" ".join(_LOC_NOISE.sub(" ", p.replace(".", "")).split()).strip(" :-")
                          for p in parts) if t]
    if not tokens:
        return False
    for t in tokens:
        if t in REGIONS_WITHOUT_KZ:
            continue
        code = country_code(t)
        if code is None or code == country:
            return False
    return True


def hidden_reason(job: Job, cfg: FilterConfig) -> str | None:
    if job.work_format in ("hybrid", "office"):
        return job.work_format
    text = f"{job.location_raw or ''} {job.title}"
    if HYBRID_RE.search(text) or OFFICE_DAYS_RE.search(text):
        return "hybrid"
    if OFFICE_RE.search(text) and not REMOTE_RE.search(text):
        return "office"

    if is_non_it_title(job.title):
        return "non_it"

    if job.remote_scope == "restricted":
        return "restricted"
    if job.countries and cfg.country not in job.countries:  # whatever the scope
        return "restricted"

    return stopword_reason(job.title, job.description_text, cfg.stopwords)


def stopword_reason(title: str | None, description_text: str | None,
                    stopwords: list[str]) -> str | None:
    """`stopword:<word>` for the first stopword found in the title or description."""
    haystack = f"{title or ''} {description_text or ''}"
    for w in stopwords:
        if w and _has(haystack, w):
            return f"stopword:{w.lower()}"
    return None


# Role phrases: non-IT whatever else the title says ("Sales Engineer", "Customer Success Engineer").
NON_IT_ROLE_WORDS = [
    "sales", "account executive", "account manager", "account director",
    "business development", "sales development", "presales", "pre-sales",
    "customer success", "customer support", "customer service", "technical support",
    "support specialist", "recruiter", "art director", "creative director", "copywriter",
    "content writer", "community manager", "proposal", "executive assistant",
    "office manager", "nurse", "therapist", "physician", "teacher", "accountant",
    # Russian; a trailing * matches any ending («маркетолог*» → «маркетологом»)
    "маркетолог*", "бухгалтер*", "рекрутер*", "менеджер* по работе с клиентами",
    "по развитию бизнеса", "арт-директор*",
]
# Domain words: non-IT only when the title has no strong IT noun
# ("Medical Software Engineer" stays, "Medical Billing Specialist" goes).
NON_IT_DOMAIN_WORDS = [
    "marketing", "communications", "finance", "accounting", "legal", "counsel", "hr",
    "talent", "people partner", "clinical", "medical", "tutor", "operations manager",
    "compensation", "internal controls", "sox", "media specialist", "support engineer",
    "solutions engineer", "solutions consultant",
    "voice actor", "ai trainer", "procurement",
    "продаж*",  # «Менеджер по продажам» goes, «Разработчик CRM для отдела продаж» stays
    # hh employers file furniture design under the IT role «Дизайнер, художник»
    "мебел*", "конструктор*", "поддержк*", "продвижени*", "партнерск*", "партнёрск*",
]


def _word_pattern(w: str) -> str:
    return re.escape(w).replace(r"\*", r"\w*")


def _words_re(words: list[str]) -> re.Pattern:
    return re.compile(r"(?<!\w)(?:" + "|".join(_word_pattern(w) for w in words) + r")(?!\w)",
                      re.IGNORECASE)


_ROLE_RE = _words_re(NON_IT_ROLE_WORDS)
_DOMAIN_RE = _words_re(NON_IT_DOMAIN_WORDS)
_STRONG_IT_RE = re.compile(
    r"(?<!\w)(?:software|developer|programmer|devops|sre|site reliability|back-?end|"
    r"front-?end|full[ -]?stack|data (?:engineer|scientist)|machine learning|ml|platform|"
    r"infrastructure|cloud|security|qa|it|tech|linux|kernel|"
    r"разработ\w*|программист\w*|тестировщик\w*|аналитик\w*)(?!\w)", re.IGNORECASE)


def is_non_it_title(title: str) -> bool:
    """True when the title names a clearly non-IT role (sales, support, HR, ...)."""
    title = title or ""
    if _ROLE_RE.search(title):
        return True
    return _DOMAIN_RE.search(title) is not None and _STRONG_IT_RE.search(title) is None
