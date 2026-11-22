"""Your profile from Resume Studio: the default master resume, fetched over its HTTP API.

Only what matching needs is kept (title, roles, skills, years of experience, languages);
name and contacts are not copied. A snapshot lives in the `resume` setting, so Job Finder
works when Resume Studio is not running.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx

from . import db
from .normalize import STACK_TERMS, extract_stack

log = logging.getLogger(__name__)
TIMEOUT = 10
SAMPLE_FILES = {"sample-resume.pdf"}


class ResumeUnavailable(Exception):
    pass


# ------------------------------------------------------------------ years

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "июн": 6, "июл": 7, "авг": 8,
    "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
_PRESENT = re.compile(r"present|now|current|today|н\.?\s?в\.?|настоящ\w*|сейчас|текущ\w*", re.I)
_POINT = re.compile(r"(?:(?P<mname>[a-zа-яё]{3})[a-zа-яё]*\.?\s+|(?P<mnum>\d{1,2})[./])?(?P<year>(?:19|20)\d{2})",
                    re.I)


def _points(text: str) -> list[tuple[int, bool]]:
    """(month index, has month) for every date in the text, in order."""
    out = []
    for m in _POINT.finditer(text):
        month = None
        if m.group("mname"):
            month = _MONTHS.get(m.group("mname").lower())
        elif m.group("mnum") and 1 <= int(m.group("mnum")) <= 12:
            month = int(m.group("mnum"))
        out.append((int(m.group("year")) * 12 + (month or 1) - 1, month is not None))
    return out


def _span(text: str, now_idx: int) -> tuple[int, int] | None:
    """[start, end) in months for «Jan 2020 - Present», «2019 – 2021», «03.2022 - н.в.»."""
    points = _points(text or "")
    if not points:
        return None
    start, _ = points[0]
    if len(points) >= 2:
        end, has_month = points[1]
        end += 1 if has_month else 12  # the end month (or the whole end year) counts
    elif _PRESENT.search(text) or re.search(r"\b(?:since|from|с)\b", text, re.I):
        end = now_idx
    else:
        end = start + (1 if points[0][1] else 12)  # «2018» alone: that year
    end = min(end, now_idx)
    return (start, end) if end > start else None


def experience_years(periods: list[str], now: datetime) -> float | None:
    """Total years covered by the periods, overlaps counted once; None when none parse."""
    now_idx = now.year * 12 + now.month - 1
    spans = sorted(s for s in (_span(p, now_idx) for p in periods) if s)
    if not spans:
        return None
    months, cur_start, cur_end = 0, *spans[0]
    for s, e in spans[1:]:
        if s > cur_end:
            months += cur_end - cur_start
            cur_start, cur_end = s, e
        else:
            cur_end = max(cur_end, e)
    months += cur_end - cur_start
    return round(months / 12, 1)


# ---------------------------------------------------------------- profile

def _skill_name(skill: str) -> str:
    return STACK_TERMS.get(skill.strip().lower(), skill.strip())


def build_profile(data: dict, now: datetime) -> dict:
    """What matching uses from a Resume Studio `processed_data` object."""
    data = data or {}
    jobs = [e for e in data.get("workExperience") or [] if isinstance(e, dict)]
    text = "\n".join([data.get("summary") or ""] + [
        "\n".join([e.get("title") or ""] + [d for d in e.get("description") or [] if isinstance(d, str)])
        for e in jobs])
    skills: list[str] = []
    for s in [_skill_name(s) for s in data.get("skills") or [] if isinstance(s, str) and s.strip()] \
            + extract_stack(text):
        if s.lower() not in {x.lower() for x in skills}:
            skills.append(s)
    info = data.get("personalInfo") or {}
    return {
        "title": (info.get("title") or "").strip(),
        "roles": [e["title"].strip() for e in jobs if (e.get("title") or "").strip()],
        "skills": skills,
        "years": experience_years([e.get("years") or "" for e in jobs], now),
        "languages": [x for x in data.get("languages") or [] if isinstance(x, str)],
    }


# ------------------------------------------------------------------ fetch

def _get(client: httpx.Client, url: str):
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        raise ResumeUnavailable(f"Resume Studio не отвечает ({url}): {e}") from e
    if r.status_code != 200:
        raise ResumeUnavailable(f"Resume Studio ответил HTTP {r.status_code} на {url}")
    try:
        return r.json().get("data")
    except (ValueError, AttributeError) as e:
        raise ResumeUnavailable(f"Resume Studio вернул не JSON на {url}") from e


def _pick(items) -> dict | None:
    ready = [i for i in items or [] if isinstance(i, dict) and i.get("processing_status") == "ready"]
    for test in (lambda i: i.get("is_default_master"), lambda i: i.get("is_master"), lambda i: True):
        found = [i for i in ready if test(i)]
        if found:
            return found[0]
    return None


def refresh(conn, now: datetime, transport: httpx.BaseTransport | None = None) -> dict:
    """Fetch the default master resume and store the snapshot; raises ResumeUnavailable."""
    base = (db.get_setting(conn, "resume_studio_url") or "").rstrip("/")
    with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
        item = _pick(_get(client, f"{base}/api/v1/resumes"))
        if item is None:
            raise ResumeUnavailable("В Resume Studio нет готового резюме: загрузи его и дождись разбора")
        full = _get(client, f"{base}/api/v1/resumes/{item['resume_id']}") or {}
    data = full.get("processed_data")
    if not isinstance(data, dict):
        raise ResumeUnavailable("Resume Studio отдал резюме без разобранных данных")
    filename = item.get("filename") or full.get("filename") or ""
    snap = {"resume_id": item["resume_id"], "filename": filename,
            "is_sample": filename.lower() in SAMPLE_FILES,
            "updated_at": item.get("updated_at"), "fetched_at": now.isoformat(),
            "profile": build_profile(data, now)}
    db.set_setting(conn, "resume", snap)
    return snap


def refresh_quietly(conn, now: datetime, transport: httpx.BaseTransport | None = None) -> bool:
    """refresh() for the scheduled collect: a stopped Resume Studio is not an error."""
    try:
        refresh(conn, now, transport)
        return True
    except ResumeUnavailable as e:
        log.info("резюме не обновлено: %s", e)
    except Exception:
        log.warning("резюме не обновлено", exc_info=True)
    return False
