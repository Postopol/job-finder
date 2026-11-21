from __future__ import annotations

from ..http import PoliteClient
from ..models import Job
from . import register
from .base import ParseError, Source, paged
from .geo import countries_from, utc_from_iso

SITE = "https://getmatch.ru"
URL = SITE + "/api/offers"
LIST_KEY = "offers"
LIMIT = 100
_WORLD = "Весь мир"
# Russian country names used by getmatch -> ISO-2 (not covered by the English table in geo.py)
RU_COUNTRIES = {
    "россия": "RU", "казахстан": "KZ", "беларусь": "BY", "белоруссия": "BY", "украина": "UA",
    "армения": "AM", "грузия": "GE", "азербайджан": "AZ", "узбекистан": "UZ", "кыргызстан": "KG",
    "киргизия": "KG", "таджикистан": "TJ", "молдова": "MD", "сербия": "RS", "турция": "TR",
    "оаэ": "AE", "польша": "PL", "германия": "DE", "кипр": "CY", "черногория": "ME",
    "болгария": "BG", "вьетнам": "VN", "таиланд": "TH", "израиль": "IL", "сша": "US",
}
_CURRENCIES = {"RUR": "RUB"}


def parse_payload(payload) -> list[dict]:
    node = payload.get(LIST_KEY) if isinstance(payload, dict) else None
    if not isinstance(node, list):
        raise ParseError(f"нет списка {LIST_KEY}")
    return [j for j in node if isinstance(j, dict)]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _remote_requirements(item: dict) -> list[dict]:
    reqs = item.get("location_requirements")
    return [r for r in reqs if isinstance(r, dict) and r.get("format") == "remote"] \
        if isinstance(reqs, list) else []


def _scope(reqs: list[dict]) -> tuple[str, list[str]]:
    reqs = [r for r in reqs if not r.get("exclude")]
    if not reqs:
        return "unknown", []
    if any(r.get("location_id") == "_cu-world" or r.get("country") == _WORLD for r in reqs):
        return "worldwide", []
    codes: list[str] = []
    for r in reqs:
        name = str(r.get("country") or "").strip()
        code = RU_COUNTRIES.get(name.lower()) or (countries_from([name])[0] or [None])[0]
        if code is None:
            return "unknown", []  # never narrow below what the site gave
        if code not in codes:
            codes.append(code)
    return "countries", codes


class Getmatch(Source):
    name = "getmatch"
    lang = "ru"
    full_listing = False
    method = "JSON сайта"

    def parse_item(self, item: dict) -> Job | None:
        title, url = item.get("position"), item.get("url")
        if not title or not url or item.get("id") is None or item.get("is_active") is False:
            return None
        remote = _remote_requirements(item)
        if not remote:
            return None
        scope, codes = _scope(remote)
        lo, hi = _amount(item.get("salary_display_from")), _amount(item.get("salary_display_to"))
        has_salary = (lo is not None or hi is not None) and not item.get("salary_hidden")
        currency = str(item.get("salary_currency") or "").upper() or None
        description = str(item.get("offer_description") or "").strip()
        company = item.get("company")
        skills = item.get("skills_objects")
        places = [str(r["city"]) for r in remote if r.get("city")]
        return Job(
            source=self.name, source_id=str(item["id"]), url=SITE + str(url), title=title,
            company=company.get("name") if isinstance(company, dict) else None, lang=self.lang,
            description_html=description.replace("\n", "<br>"), description_text="",
            salary_min=lo if has_salary else None, salary_max=hi if has_salary else None,
            salary_currency=_CURRENCIES.get(currency, currency) if has_salary else None,
            salary_period="month" if has_salary else None,
            location_raw=", ".join(places) or None, work_format="remote",
            remote_scope=scope, countries=codes,
            stack=[str(s["name"]) for s in skills if isinstance(s, dict) and s.get("name")]
            if isinstance(skills, list) else [],
            published_at=utc_from_iso(item.get("published_at")), raw=item)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        def page(n: int) -> list[dict]:
            params = {"pa": "all", "limit": LIMIT, "offset": (n - 1) * LIMIT}
            return parse_payload(client.get(URL, params=params).json())

        return paged(page, self.parse_item, known, int(settings.get("max_pages", 5)))


SOURCE = register(Getmatch())
