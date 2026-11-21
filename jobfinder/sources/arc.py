from __future__ import annotations

import html as _html
import logging
import re

from ..http import PoliteClient, SourceError
from ..models import Job
from . import register
from .base import ParseError, Source, describe_new, next_data, paged
from .geo import utc_from_epoch

log = logging.getLogger(__name__)
URL = "https://arc.dev/remote-jobs"
DETAIL_URL = "https://arc.dev/remote-jobs/details/{slug}-{key}"
LIST_PATH = ("props", "pageProps", "arcJobs")  # the page also has externalJobs (aggregated, mostly marketing)
_SENIORITY = {"junior": "junior", "entry": "junior", "mid": "middle", "middle": "middle",
              "senior": "senior", "lead": "lead", "manager": "lead"}
_OFFSET = re.compile(r"^([+-])(\d{1,2}):?(\d{2})?$")


def parse_payload(page_html: str) -> list[dict]:
    node = next_data(page_html)
    for key in LIST_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, list):
        raise ParseError(f"нет списка {'.'.join(LIST_PATH)}")
    return [j for j in node if isinstance(j, dict)]


def _tz(item: dict) -> list[str]:
    if item.get("clientTimeZoneRestriction") not in ("overlap", "strict"):
        return []
    m = _OFFSET.match(str(item.get("timeZoneOffset") or ""))
    if not m:
        return []
    hours = int(m.group(2)) + int(m.group(3) or 0) / 60
    return [f"UTC{-hours if m.group(1) == '-' else hours:+g}"]


def _amount(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _salary(item: dict) -> tuple[int | None, int | None, str | None]:
    lo, hi = _amount(item.get("minAnnualSalary")), _amount(item.get("maxAnnualSalary"))
    if lo or hi:
        return lo, hi, "year"
    lo, hi = _amount(item.get("minHourlyRate")), _amount(item.get("maxHourlyRate"))
    return (lo, hi, "hour") if lo or hi else (None, None, None)


def text_to_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{_html.escape(p).replace(chr(10), '<br>')}</p>" for p in paras)


class Arc(Source):
    name = "arc"
    lang = "en"
    full_listing = False
    detail_pages = True
    method = "JSON сайта"

    def parse_item(self, item: dict) -> Job | None:
        title, slug, key = item.get("title"), item.get("urlString"), item.get("randomKey")
        if not title or not slug or not key:
            return None
        required = [c.upper() for c in item.get("requiredCountries") or [] if isinstance(c, str)]
        lo, hi, period = _salary(item)
        company = item.get("company")
        return Job(
            source=self.name, source_id=str(key), url=DETAIL_URL.format(slug=slug, key=key),
            title=title, company=company.get("name") if isinstance(company, dict) else None,
            lang=self.lang, salary_min=lo, salary_max=hi,
            salary_currency="USD" if period else None, salary_period=period,
            work_format="remote", remote_scope="countries" if required else "worldwide",
            countries=required, timezones=_tz(item),
            seniority=_SENIORITY.get(str(item.get("experienceLevel")).lower()),
            stack=[c["name"] for c in item.get("categories") or [] if isinstance(c, dict) and c.get("name")],
            published_at=utc_from_epoch(item.get("postedAt")), raw=item)

    def _describe(self, client: PoliteClient, job: Job) -> None:
        try:
            job_data = next_data(client.get(job.url).text)["props"]["pageProps"]["job"]
            text = job_data.get("description")
        except SourceError as e:
            log.info("%s: описание %s не загружено: %s", self.name, job.source_id, e)
            return
        except (ParseError, KeyError, TypeError, AttributeError) as e:
            log.warning("%s: формат страницы вакансии %s изменился: %r", self.name, job.source_id, e)
            return
        if isinstance(text, str) and text.strip():
            job.description_text = text
            job.description_html = text_to_html(text)

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        jobs = paged(lambda n: parse_payload(client.get(URL).text), self.parse_item, known, 1)
        return describe_new(jobs, known, wants, lambda job: self._describe(client, job), self.name)


SOURCE = register(Arc())
