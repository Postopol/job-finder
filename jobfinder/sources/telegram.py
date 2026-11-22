"""Public Telegram channels with job posts, read from the web preview t.me/s/<channel>.

The preview needs no account: it shows the last ~20 posts, `?before=<id>` pages back.
Posts are free text with a loose template (title line, «Компания:», «Формат:», «ЗП:»,
hashtags), so they are parsed by rules; résumés, digests and ads are skipped.
"""
from __future__ import annotations

import logging
import re

from selectolax.lexbor import LexborHTMLParser

from ..http import PoliteClient, SourceBlocked, SourceError
from ..models import Job
from ..normalize import html_to_text
from . import register
from .base import ParseError, Source
from ..filters import REGIONS_WITHOUT_KZ
from .geo import country_code, split_places, utc_from_iso

log = logging.getLogger(__name__)
PAGE_URL = "https://t.me/s/{channel}"
POST_URL = "https://t.me/{channel}/{id}"
MAX_PAGES = 3  # per channel and run; later runs stop at the first already seen post

_NAME = re.compile(r"[a-z][a-z0-9_]{3,31}")
_LINK = re.compile(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]+)(?:/\d+)?/?$")


def channel_name(text: str | None) -> str | None:
    """«opento_dev», «@opento_dev», «https://t.me/s/opento_dev» → «opento_dev»; else None."""
    raw = (text or "").strip()
    m = _LINK.match(raw)
    name = (m.group(1) if m else raw.lstrip("@")).lower()
    return name if _NAME.fullmatch(name) else None


# ------------------------------------------------------------------ page

def parse_payload(page_html: str) -> list[dict]:
    """Text posts of a channel preview page, oldest first.

    A page without the channel header and without posts means the channel does not
    exist, is private or has the preview turned off.
    """
    tree = LexborHTMLParser(page_html)
    posts = tree.css(".tgme_widget_message[data-post]")
    if not posts and tree.css_first(".tgme_channel_info") is None:
        raise ParseError("канал недоступен: нет такого, закрыт или без веб-превью")
    out = []
    for post in posts:
        channel, _, msg_id = (post.attributes.get("data-post") or "").partition("/")
        # direct child: a reply quote inside the bubble has its own message_text
        text = post.css_first(".tgme_widget_message_bubble > .tgme_widget_message_text")
        if not channel or not msg_id.isdigit() or text is None:
            continue  # photo/video-only posts
        when = post.css_first(".tgme_widget_message_date time")
        out.append({"channel": channel.lower(), "id": int(msg_id), "html": text.html or "",
                    "published_at": when.attributes.get("datetime") if when else None})
    return out


# ------------------------------------------------------------------ post

# résumés and digests (a digest repeats posts of the same channel, one line per job)
_SKIP_TAGS = {"резюме", "resume", "cv", "ищу_работу", "ищуработу", "lookingforjob",
              "opentowork", "ищу", "дайджест", "digest"}
_VACANCY_TAGS = {"вакансия", "vacancy", "job", "hiring", "вакансии"}
_REMOTE_TAGS = {"remote", "удаленка", "удалёнка", "удаленно", "удалённо", "удалённая_работа",
                "удаленная_работа", "remotework"}
_HYBRID_TAGS = {"hybrid", "гибрид"}
_OFFICE_TAGS = {"office", "офис"}
_META = ("публикатор:", "обсуждение:", "автор:", "источник:")
_SKIP_START = re.compile(r"^(?:дайджест|резюме|подборка)\b", re.I)

_FIELDS = {
    "title": ("вакансия", "позиция", "должность", "position", "role", "vacancy"),
    "company": ("компания", "заказчик", "работодатель", "company", "employer"),
    "salary": ("зп", "з/п", "зарплата", "вилка", "вилка зп", "вилка з/п", "уровень зп",
               "оклад", "доход", "salary", "compensation", "бюджет"),
    "format": ("формат", "формат работы", "format", "тип работы", "work format"),
    "location": ("локация", "локации", "location", "locations", "город", "место работы",
                 "страна", "регион"),
    "citizenship": ("гражданство", "citizenship", "резидентство", "локация/гражданство",
                    "гражданство/локация"),
}
_FIELD_OF = {k: name for name, keys in _FIELDS.items() for k in keys}
_FIELD_LINE = re.compile(r"^([^\W\d][\w ./]{0,24}?)\s*:\s*(.*)$")

_BULLET = re.compile(r"^[^\w#@(«\"$€£₽]+")
_TRAIL = re.compile(r"[\s;.,:\-–—]*[^\w)»\"+#]*$")  # keeps «C++», «C#»
_TAG = re.compile(r"#(\w+)")

_ROLE = re.compile(
    r"(?<!\w)(?:engineer|developer|dev|programmer|devops|sre|qa|aqa|tester|analyst|designer|"
    r"architect|scientist|researcher|admin\w*|lead|head|cto|manager|owner|specialist|"
    r"frontend|front-end|backend|back-end|full-?stack|data|ml|ai|"
    r"разработчи\w*|программист\w*|инженер\w*|тестировщи\w*|аналитик\w*|дизайнер\w*|"
    r"архитектор\w*|администратор\w*|менеджер\w*|руководител\w*|лид|тимлид|техлид|"
    r"специалист\w*|исследовател\w*|devrel)(?!\w)", re.I)

# ads and announcements that name a role: «QA-митап», «запустил QA Sprint», «вебинар для аналитиков»
_TITLE_NOISE = re.compile(
    r"(?<!\w)(?:митап\w*|meetup|вебинар\w*|webinar|интенсив\w*|курс\w*|спринт\w*|sprint|"
    r"запустил\w*|приглаша\w*|эфир\w*|конференц\w*|хакатон\w*|hackathon|дебат\w*|оффер\w*)(?!\w)",
    re.I)
# a company is a name, not a role or a sentence («Healz.ai», «Ryze AI» are fine)
_COMPANY_ROLE = re.compile(
    r"(?<!\w)(?:engineer|developer|programmer|analyst|designer|manager|lead|head|owner|"
    r"director|cto|ceo|разработчи\w*|инженер\w*|аналитик\w*|менеджер\w*|руководител\w*)(?!\w)",
    re.I)
# «Компания: NDA (FinTech)», «Компания: Стартап.» name no company
_PLACEHOLDER_COMPANY = re.compile(r"^(?:nda|стартап|startup|конфиденциально|не раскрыва\w*|"
                                  r"не указан\w*|секрет\w*)(?!\w)", re.I)
_LINK_TEXT = re.compile(r"^(?:смотреть|откликнуться|подробнее|читать|apply|details)\b", re.I)
_DOT_THOUSANDS = re.compile(r"(?<=\d)\.(?=\d{3}(?!\d))")  # «$5.000», «200.000»

_HYBRID = re.compile(r"(?<!\w)(?:hybrid|гибрид\w*)(?!\w)", re.I)
_OFFICE = re.compile(r"(?<!\w)(?:office|on-?site|офис\w*|в офисе)(?!\w)", re.I)
_REMOTE = re.compile(r"(?<!\w)(?:remote|удал[её]нн?\w*|дистанц\w*|full[- ]remote)(?!\w)", re.I)
_RELOCATION = re.compile(r"(?<!\w)(?:релокац\w*|relocation|relocate)(?!\w)", re.I)
_WORLDWIDE = re.compile(r"(?<!\w)(?:из любой (?:страны|точки мира)|любая страна|worldwide|"
                        r"anywhere|весь мир)(?!\w)", re.I)
# «удалённо по России», «из РФ», «Гражданство: Россия, Беларусь»
_COUNTRY_WORDS = (("RU", r"росси\w*|рф"), ("BY", r"беларус\w*|белорус\w*|рб"),
                  ("KZ", r"казахстан\w*|рк"), ("UZ", r"узбекистан\w*"), ("AM", r"армени\w*"),
                  ("GE", r"грузи[ия]\w*"), ("KG", r"кыргызстан\w*|киргиз\w*"),
                  ("RS", r"серби\w*"), ("UA", r"украин\w*"))
_COUNTRY_RE = [(code, re.compile(rf"(?<!\w)(?:{rx})(?!\w)", re.I)) for code, rx in _COUNTRY_WORDS]
# «удаленно (кроме РФ и РБ)», «офис в Армении»: countries named here are not a limit
_NOT_LIMIT = re.compile(r"(?<!\w)(?:кроме|except|офис\w*|office)(?!\w)[^;/)]*", re.I)
_NO_SALARY = re.compile(r"не указан|по договор|обсуждается|competitive|tbd", re.I)
_CYRILLIC = re.compile(r"[а-яё]", re.I)
_LATIN = re.compile(r"[a-z]", re.I)


def _clean(line: str) -> str:
    return _TRAIL.sub("", _BULLET.sub("", line)).strip()


def _field(line: str) -> tuple[str, str] | None:
    m = _FIELD_LINE.match(line)
    if not m:
        return None
    name = _FIELD_OF.get(" ".join(m.group(1).lower().split()))
    return (name, m.group(2).strip().rstrip(" ;.,")) if name else None


def _title_text(line: str) -> str:
    """Title line without inline hashtags, link texts («| Смотреть вакансию») and emoji."""
    parts = [p for p in _TAG.sub("", line).split(" | ") if not _LINK_TEXT.match(_clean(p))]
    return _clean(" | ".join(parts))


def _title_ok(title: str) -> bool:
    return (3 <= len(title) <= 120 and not title.rstrip().endswith(("!", "?"))
            and _ROLE.search(title) is not None and not _TITLE_NOISE.search(title))


def _company_ok(company: str | None) -> str | None:
    company = (company or "").strip().rstrip(".").strip()
    if _PLACEHOLDER_COMPANY.match(company) or _COMPANY_ROLE.search(company):
        return None
    return company if 0 < len(company) <= 60 else None


def _split_company(title: str) -> tuple[str, str | None]:
    """«Backend Engineer (Python / Django) / Karta.io» → (role, «Karta.io»)."""
    role, sep, company = title.rpartition(" / ")
    if sep and role.count("(") == role.count(")") and _ROLE.search(role) and _company_ok(company):
        return role.strip(), company.strip()
    return title, None


def _work_format(where: str, tags: set[str], text: str) -> str | None:
    if _HYBRID.search(where) or tags & _HYBRID_TAGS:
        return "hybrid"
    remote = _REMOTE.search(where) or tags & _REMOTE_TAGS
    if (_OFFICE.search(where) or tags & _OFFICE_TAGS) and not remote:
        return "office"
    if remote:
        return "remote"
    if _RELOCATION.search(text) and not _REMOTE.search(text):
        return "office"  # «помогают с релокацией»: the job is in the company's country
    return None


def _countries(where: str, citizenship: str) -> list[str]:
    """Countries the job is limited to: «удалённо по России», «Удаленный РФ», «Гражданство: РФ, РБ».

    Not a limit: excluded countries («кроме РФ»), the office country, a worldwide job."""
    place = "" if _WORLDWIDE.search(where) else _NOT_LIMIT.sub(" ", where)
    text = f"{place} ; {citizenship}"
    return [code for code, rx in _COUNTRY_RE if rx.search(text)]


def _is_place(line: str) -> bool:
    """A line about where to work: «Remote», «Удаленный РФ», «Europe, Poland»."""
    if any(rx.search(line) for rx in (_REMOTE, _HYBRID, _OFFICE, _WORLDWIDE, _RELOCATION)):
        return True
    if any(rx.search(line) for _, rx in _COUNTRY_RE):
        return True
    parts = [p.lower().strip(" ()") for p in split_places(line)]
    return bool(parts) and all(p in REGIONS_WITHOUT_KZ or country_code(p) for p in parts)


def _lang(text: str) -> str:
    return "ru" if len(_CYRILLIC.findall(text)) >= len(_LATIN.findall(text)) * 0.25 else "en"


class Telegram(Source):
    name = "telegram"
    lang = "ru"
    full_listing = False
    method = "Каналы Telegram"

    def parse_item(self, item: dict) -> Job | None:
        try:
            return self._parse(item)
        except Exception:  # noqa: BLE001 - an odd post must not kill the run
            return None

    def _parse(self, item: dict) -> Job | None:
        channel, msg_id, body = item.get("channel"), item.get("id"), item.get("html")
        if not channel or not isinstance(msg_id, int) or not isinstance(body, str) or not body:
            return None
        text = html_to_text(body)
        tags = {t.lower() for t in _TAG.findall(text)}
        if tags & _SKIP_TAGS:
            return None

        fields: dict[str, list[str]] = {}
        content: list[str] = []  # lines that are not meta, hashtags or known fields
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.lower().startswith(_META) or not _TAG.sub("", line).strip(" ,"):
                continue
            f = _field(_BULLET.sub("", line))
            if f:
                fields.setdefault(f[0], []).append(f[1])
            else:
                content.append(line)
        if not content and "title" not in fields:
            return None
        if content and _SKIP_START.match(_clean(content[0])):
            return None

        field_company = _company_ok(fields["company"][0]) if "company" in fields else None
        # the title is the «Вакансия:» field or the first line; a preface line
        # («Прямая вакансия от работодателя») may come before it
        if "title" in fields:
            candidates = [(_title_text(fields["title"][0]), 0)]
        else:
            candidates = [(_title_text(ln), i + 1) for i, ln in enumerate(content[:2])
                          if i == 0 or len(ln) <= 80]
        for title, start in candidates:
            company = field_company
            if "company" not in fields:
                title, company = _split_company(title)
            if _title_ok(title):
                break
        else:
            return None

        if "company" in fields:  # «Бизнес-аналитик в Unity Parent» + «Компания: Unity Parent»
            named = fields["company"][0].strip().rstrip(".").strip()
            cut = title[:-len(named) - 3].strip()
            if named and title.lower().endswith(f" в {named.lower()}") and _title_ok(cut):
                title = cut

        # the short line right under the title: «Remote», «Удалённо из любой страны», «Cyprus»
        near = [_clean(ln) for ln in content[start:start + 1] if len(ln) <= 60 and _is_place(ln)]
        where = " ; ".join(fields.get("format", []) + fields.get("location", []) + near)
        has_signal = (tags & (_VACANCY_TAGS | _REMOTE_TAGS | _HYBRID_TAGS | _OFFICE_TAGS)
                      or fields.keys() & {"title", "company", "salary", "format"}
                      or _REMOTE.search(where) or _HYBRID.search(where) or _OFFICE.search(where)
                      or _RELOCATION.search(text))
        if not has_signal:
            return None

        salary = next((_DOT_THOUSANDS.sub(" ", s) for s in fields.get("salary", [])
                       if s and not _NO_SALARY.search(s)), None)
        countries = _countries(where, " ; ".join(fields.get("citizenship", [])))
        scope = "countries" if countries else ("worldwide" if _WORLDWIDE.search(where) else "unknown")
        return Job(
            source=self.name, source_id=f"{channel}/{msg_id}",
            url=POST_URL.format(channel=channel, id=msg_id), title=title,
            company=company or None, lang=_lang(text), description_html=body,
            description_text=text, salary_raw=salary,
            location_raw=where or None,
            work_format=_work_format(where, tags, text), remote_scope=scope,
            countries=countries, stack=sorted(tags),
            published_at=utc_from_iso(item.get("published_at")), raw=item)

    # -------------------------------------------------------------- fetch

    def _channel(self, client: PoliteClient, channel: str, known: set[str],
                 pages: int) -> list[Job]:
        seen = [int(sid.split("/", 1)[1]) for sid in known
                if sid.startswith(f"{channel}/") and sid.split("/", 1)[1].isdigit()]
        newest_known = max(seen, default=0)
        url = PAGE_URL.format(channel=channel)
        out: list[Job] = []
        before: int | None = None
        for _ in range(pages):
            page = client.get(url, params={"before": before} if before else None).text
            items = parse_payload(page)
            ids = [i["id"] for i in items]
            if not items or (before is not None and min(ids) >= before):
                break
            self.last_items = (self.last_items or 0) + len(items)
            out.extend(j for j in map(self.parse_item, items) if j is not None)
            before = min(ids)
            if before <= newest_known + 1 or before <= 1:
                break
        return out

    def fetch(self, client: PoliteClient, known: set[str], wants, settings: dict) -> list[Job]:
        self.last_items = 0
        channels = [c for c in (channel_name(n) for n in settings.get("tg_channels") or []) if c]
        pages = max(1, min(int(settings.get("max_pages") or MAX_PAGES), MAX_PAGES))
        out: list[Job] = []
        opened = 0
        errors: list[str] = []
        for channel in dict.fromkeys(channels):
            try:
                jobs = self._channel(client, channel, known, pages)
            except SourceBlocked as e:
                if not opened:
                    raise
                log.warning("telegram: %s на канале %s, остальные каналы пропущены", e, channel)
                break
            except (SourceError, ParseError) as e:
                log.warning("telegram: канал %s пропущен: %s", channel, e)
                errors.append(f"{channel}: {e}")
                continue
            opened += 1
            out.extend(jobs)
        if errors and not opened:
            raise SourceError("ни один канал не открылся; " + "; ".join(errors[:3]))
        return out


SOURCE = register(Telegram())
