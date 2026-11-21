from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SCOPES = ("worldwide", "cis", "countries", "restricted", "unknown")
STATUSES = ("new", "seen", "interesting", "applied", "rejected")
CIS = {"KZ", "RU", "BY", "UZ", "KG", "AM", "AZ", "TJ", "MD", "GE"}


@dataclass
class Job:
    source: str
    source_id: str
    url: str
    title: str
    company: str | None = None
    lang: str = "en"
    description_html: str = ""
    description_text: str = ""
    salary_raw: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None  # USD, EUR, RUB, KZT, GBP
    salary_period: str | None = None  # month | year | hour
    location_raw: str | None = None
    work_format: str | None = None  # remote | hybrid | office
    remote_scope: str = "unknown"
    countries: list[str] = field(default_factory=list)  # ISO-2
    timezones: list[str] = field(default_factory=list)
    seniority: str | None = None  # junior | middle | senior | lead
    stack: list[str] = field(default_factory=list)
    published_at: datetime | None = None  # UTC-aware
    raw: dict | None = None  # source item, kept for reparse
