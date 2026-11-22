from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient, SourceBlocked
from ..models import Job

log = logging.getLogger(__name__)


class ParseError(Exception):
    def __init__(self, detail: str):
        super().__init__(f"формат страницы изменился: {detail}")


class Source(ABC):
    name: str
    lang: str
    full_listing: bool
    method: str  # «Открытый API», «RSS», «JSON сайта», «Страница сайта»
    detail_pages: bool = False  # descriptions of new jobs are loaded from detail pages
    # set by fetch(): how many items (posts, comments) it looked at, when that differs from
    # the jobs returned; 0 means «nothing to look at this time» (no «found nothing» warning)
    last_items: int | None = None

    @abstractmethod
    def parse_item(self, item: dict) -> Job | None: ...

    @abstractmethod
    def fetch(self, client: PoliteClient, known: set[str],
              wants: Callable[[Job], bool], settings: dict) -> list[Job]: ...


def paged(fetch_page: Callable[[int], list[dict]], parse: Callable[[dict], Job | None],
          known: set[str], max_pages: int) -> list[Job]:
    out: list[Job] = []
    for page in range(1, max_pages + 1):
        items = fetch_page(page)
        if not items:
            break
        hit = False
        for item in items:
            job = parse(item)
            if job is None:
                continue
            out.append(job)
            if job.source_id in known:
                hit = True
        if hit:
            break
    return out


def describe_new(jobs: list[Job], known: set[str], wants: Callable[[Job], bool],
                 describe: Callable[[Job], None], source: str) -> list[Job]:
    """Load details for new jobs that pass the filter.

    On 429/403 stop asking the site but keep every listed job: the rest are saved
    with what the listing gave (a vacancy matters more than its full description).
    """
    for i, job in enumerate(jobs):
        if job.source_id in known or not wants(job):
            continue
        before = job.description_html
        try:
            describe(job)
        except SourceBlocked as e:
            left = sum(1 for j in jobs[i:] if j.source_id not in known and wants(j))
            log.warning("%s: %s, %d вакансий сохранены без полного описания", source, e, left)
            return jobs
        if job.description_html and job.description_html != before:
            job.description_detail = True
    return jobs


def _script_json(html: str, tag_id: str):
    node = LexborHTMLParser(html).css_first(f'script#{tag_id}')
    if node is None:
        raise ParseError(f"нет тега {tag_id}")
    try:
        return json.loads(node.text(strip=False))
    except ValueError as e:
        raise ParseError(f"некорректный JSON в {tag_id}: {e}") from e


def next_data(html: str) -> dict:
    data = _script_json(html, "__NEXT_DATA__")
    if not isinstance(data, dict):
        raise ParseError("__NEXT_DATA__ не объект")
    return data


_REF_WRAPPERS = ("Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef")
_MISSING = object()


def _revive(arr, idx, memo):
    if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
        return None  # -1 undefined, -2 null, -3 NaN, ...
    if idx in memo:
        return memo[idx]
    v = arr[idx]
    if isinstance(v, list):
        if v and isinstance(v[0], str) and v[0] in _REF_WRAPPERS:
            memo[idx] = None  # cycle guard
            out = _revive(arr, v[1], memo) if len(v) > 1 else None
        elif v and v[0] == "Set":
            out = memo[idx] = []
            out.extend(_revive(arr, i, memo) for i in v[1:])
        elif v and v[0] == "Map":
            out = memo[idx] = {}
            for i in range(1, len(v) - 1, 2):
                out[str(_revive(arr, v[i], memo))] = _revive(arr, v[i + 1], memo)
        elif v and v[0] == "Date":
            out = v[1] if len(v) > 1 else None
        else:
            out = memo[idx] = []
            out.extend(_revive(arr, i, memo) for i in v)
    elif isinstance(v, dict):
        out = memo[idx] = {}
        for k, i in v.items():
            out[k] = _revive(arr, i, memo)
    else:
        out = v
    memo[idx] = out
    return out


def nuxt_data(html: str):
    arr = _script_json(html, "__NUXT_DATA__")
    if not isinstance(arr, list) or not arr:
        raise ParseError("__NUXT_DATA__ не массив")
    try:
        return _revive(arr, 0, {})
    except (IndexError, TypeError) as e:
        raise ParseError(f"битая структура __NUXT_DATA__: {e}") from e
