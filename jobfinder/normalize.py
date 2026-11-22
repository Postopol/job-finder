from __future__ import annotations

import re
from typing import NamedTuple

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .models import Job


class Salary(NamedTuple):
    min: int | None
    max: int | None
    currency: str | None
    period: str | None


# ---------------------------------------------------------------- salary

_CURRENCIES = [
    ("RUB", re.compile(r"₽|руб|\brub\b", re.I)),
    ("USD", re.compile(r"\$|\busd\b|долл", re.I)),
    ("EUR", re.compile(r"€|\beur\b|евро", re.I)),
    ("KZT", re.compile(r"₸|тенге|\bkzt\b", re.I)),
    ("GBP", re.compile(r"£|\bgbp\b", re.I)),
]
_PERIODS = [
    ("hour", re.compile(r"\b(?:hour|hourly|hr|h)\b|(?<!\w)(?:по)?час(?:ов\w*|а|ы|у)?(?!\w)", re.I)),
    ("month", re.compile(r"\b(?:month|monthly|mo)\b|(?<!\w)(?:по)?мес(?:яц\w*|яч\w*)?(?!\w)", re.I)),
    ("year", re.compile(r"\b(?:year|yearly|yr|annual|annually)\b|(?<!\w)(?:годов\w*|год(?:а|у)?)(?!\w)|/\s*y\b", re.I)),
]
_NUMBER = re.compile(
    r"(\d{1,3}(?:[ ,]\d{3})+|\d+(?:\.\d+)?)\s*(k\b|тыс\b\.?)?", re.I
)
_FROM = re.compile(r"\bот\b|\bfrom\b|\bmin\b", re.I)
_UPTO = re.compile(r"\bдо\b|\bup\s*to\b|\bmax\b", re.I)


def _clean(text: str) -> str:
    text = re.sub(r"[     ]", " ", text)
    return re.sub(r"[–—−]", "-", text)


def _to_int(num: str, mult: str | None) -> int:
    value = float(re.sub(r"[ ,]", "", num))
    if mult:
        value *= 1000
    return int(round(value))


def parse_salary(text: str | None) -> Salary | None:
    try:
        return _parse_salary(text)
    except Exception:
        return None


def _parse_salary(text: str | None) -> Salary | None:
    if not text:
        return None
    text = _clean(text)
    currency = next((code for code, rx in _CURRENCIES if rx.search(text)), None)
    if currency is None:
        return None
    found = _NUMBER.findall(text)[:2]
    if not found:
        return None
    # "$70-90k": the multiplier on the last number applies to the first too
    mults = [m for _, m in found]
    if len(found) == 2 and mults[1] and not mults[0]:
        first = float(re.sub(r"[ ,]", "", found[0][0]))
        if first < 1000:
            mults[0] = mults[1]
    values = [_to_int(n, m) for (n, _), m in zip(found, mults)]

    if len(values) == 2:
        lo, hi = sorted(values)
    elif _UPTO.search(text) and not _FROM.search(text):
        lo, hi = None, values[0]
    else:
        lo, hi = values[0], None

    period = next((name for name, rx in _PERIODS if rx.search(text)), None)
    if period is None:
        amount = hi if hi is not None else lo
        if currency in ("RUB", "KZT"):
            period = "month"
        else:
            period = "year" if amount >= 20000 else "month"
    return Salary(lo, hi, currency, period)


# --------------------------------------------- salary inside the description

# One amount with a currency sign: «$85,389», «$150K», «€4,000», «$95,000.00»; not «$10M».
# Digit runs are bounded and unambiguous (no nested repeats): descriptions come from other
# sites, and «$1,1,1,1,…» must not make the regex backtrack for seconds.
_NUM = r"(?:\d{1,3}(?:,\d{3}){1,4}|\d{1,9})(?![\d,]\d)(?:\.\d{1,2})?"
_AMOUNT = rf"[$€£]\s?{_NUM}\s?[kK]?(?!\s?(?:[mMbB]\b|million|billion|bn\b))"
_BARE = rf"{_NUM}\s?[kK]?"  # second end of «$180–250k»
_UNIT = (r"(?:\s?(?:usd|eur|gbp))?(?:\s?(?:/\s?(?:yr|year|hr|hour|h|mo|month)\b|per\s+(?:year|annum|hour|month)"
         r"|a\s+year|an\s+hour|annually|hourly|monthly))?")
_SEP = r"\s?(?:-|–|—|to|-to-|and)\s?"
_RANGE = re.compile(rf"(?:{_AMOUNT}){_UNIT}{_SEP}(?:{_AMOUNT}|{_BARE}){_UNIT}", re.I)
_SINGLE = re.compile(rf"{_AMOUNT}{_UNIT}", re.I)
_SALARY_WORDS = re.compile(r"(?<!\w)(?:salary|compensation|pay|base|rate|ote|wage|earnings|"
                           r"зарплат\w*|оклад\w*|вилка)(?!\w)", re.I)
_CENTS = re.compile(r"(\d{1,3}(?:,\d{3})+)\.\d{1,2}(?!\d)")
MAX_SALARY_SCAN = 30_000  # characters of a description searched for a salary
# a sane salary per period, in the currency's units (filters «$6 to $9» and benefits)
_SANE = {"year": (10_000, 2_000_000), "month": (500, 100_000), "hour": (5, 1_000)}


def _sane(snippet: str) -> bool:
    sal = parse_salary(snippet)
    if sal is None:
        return False
    lo, hi = _SANE[sal.period]
    return all(lo <= v <= hi for v in (sal.min, sal.max) if v is not None)


def salary_from_text(text: str | None) -> str | None:
    """The first salary written inside a description: «Salary Range: $85,389 - $116,975» →
    «$85,389 - $116,975». A range counts anywhere; a single amount only right after a salary
    word («Compensation: €4,000 per month»), so benefits like «$500 for your workstation» don't."""
    text = (text or "")[:MAX_SALARY_SCAN]
    for m in _RANGE.finditer(text):
        snippet = _CENTS.sub(r"\1", m.group(0).strip())
        if _sane(snippet):
            return snippet
    for m in _SINGLE.finditer(text):
        if _SALARY_WORDS.search(text[max(0, m.start() - 40):m.start()]):
            snippet = _CENTS.sub(r"\1", m.group(0).strip())
            if _sane(snippet):
                return snippet
    return None


# ------------------------------------------------------------- seniority

_LEAD = re.compile(
    r"(?<!\w)(?:team\s*lead|tech\s*lead|lead|head\s+of|principal|staff|director|"
    r"engineering\s+manager|тимлид|тим-лид|лид|руководитель|директор\w*)(?!\w)",
    re.I,
)
_SENIOR = re.compile(
    r"(?<!\w)(?:senior|sr\.?|старший|ведущий|сеньор|сениор)(?!\w)", re.I
)
_MIDDLE = re.compile(r"(?<!\w)(?:middle|mid|mid-level|мидл|миддл)(?!\w)", re.I)
_JUNIOR = re.compile(
    r"(?<!\w)(?:junior|jr\.?|jun|intern|trainee|младший|джуниор|джун|стажёр|стажер)(?!\w)",
    re.I,
)


# Required experience in the description: "5+ years of experience", "Experience: 3 years",
# «опыт работы от 3 лет», «3+ года опыта». A range counts by its lower bound.
_N = r"(\d{1,2})\s*\+?\s*(?:(?:-|–|—|to|до)\s*\d{1,2}\s*\+?\s*)?"
_YEARS_RE = (
    re.compile(_N + r"(?:years?|yrs?)\b(?:\s+of)?(?:[\s,]+[\w-]+){0,3}?[\s,]+experience\b", re.I),
    re.compile(r"\bexperience\b\s*(?:of|:|-|–)?\s*(?:at\s+least|minimum|min\.?|over|"
               r"more\s+than)?\s*" + _N + r"(?:years?|yrs?)\b", re.I),
    re.compile(r"(?<!\w)опыт\w*(?:\s+[а-яё-]+){0,3}?\s+(?:от|не\s+менее|более|свыше|минимум)?\s*"
               + _N + r"(?:год|года|лет)(?!\w)", re.I),
    re.compile(_N + r"(?:год|года|лет)(?!\w)(?:\s+[а-яё-]+){0,2}?\s+опыт", re.I),
)
_MAX_YEARS = 15  # "20 years of experience of our team" is about the company


def years_required(text: str) -> int | None:
    """The largest experience requirement in years found in the text, or None."""
    found = [int(m.group(1)) for rx in _YEARS_RE for m in rx.finditer(text or "")]
    found = [n for n in found if n <= _MAX_YEARS]
    return max(found) if found else None


def _level_by_years(years: int) -> str:
    if years <= 1:
        return "junior"
    return "middle" if years <= 3 else "senior"


def detect_seniority(title: str, text: str = "") -> str | None:
    """Level from the title; else from the required years of experience; else from level
    words in the text (the weakest hint: "you will work with senior engineers")."""
    if _LEAD.search(title or ""):
        return "lead"
    for name, rx in (("senior", _SENIOR), ("middle", _MIDDLE), ("junior", _JUNIOR)):
        if rx.search(title or ""):
            return name
    years = years_required(text)
    if years is not None:
        return _level_by_years(years)
    for name, rx in (("senior", _SENIOR), ("middle", _MIDDLE), ("junior", _JUNIOR)):
        if rx.search(text or ""):
            return name
    return None


# ----------------------------------------------------------------- stack

STACK_TERMS: dict[str, str] = {
    # languages
    "python": "Python", "java": "Java", "javascript": "JavaScript", "js": "JavaScript",
    "typescript": "TypeScript", "ts": "TypeScript", "go": "Go", "golang": "Go",
    "rust": "Rust", "c++": "C++", "cpp": "C++", "c#": "C#", "csharp": "C#",
    ".net": ".NET", "dotnet": ".NET", "asp.net": "ASP.NET", "php": "PHP",
    "ruby": "Ruby", "kotlin": "Kotlin", "swift": "Swift", "scala": "Scala",
    "elixir": "Elixir", "sql": "SQL", "bash": "Bash",
    # frameworks
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "spring": "Spring",
    "rails": "Rails", "ruby on rails": "Rails", "laravel": "Laravel",
    "react": "React", "reactjs": "React", "react.js": "React", "vue": "Vue",
    "vue.js": "Vue", "vuejs": "Vue", "angular": "Angular", "svelte": "Svelte",
    "next.js": "Next.js", "nextjs": "Next.js", "node.js": "Node.js",
    "nodejs": "Node.js", "express": "Express", "nestjs": "NestJS", "nest.js": "NestJS",
    # databases
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL", "mysql": "MySQL",
    "mariadb": "MariaDB", "sqlite": "SQLite", "mongodb": "MongoDB", "mongo": "MongoDB",
    "redis": "Redis", "clickhouse": "ClickHouse", "elasticsearch": "Elasticsearch",
    "cassandra": "Cassandra", "oracle": "Oracle", "snowflake": "Snowflake",
    # messaging
    "kafka": "Kafka", "rabbitmq": "RabbitMQ", "graphql": "GraphQL", "grpc": "gRPC",
    # cloud / devops
    "aws": "AWS", "gcp": "GCP", "azure": "Azure", "docker": "Docker",
    "kubernetes": "Kubernetes", "k8s": "Kubernetes", "terraform": "Terraform",
    "ansible": "Ansible", "jenkins": "Jenkins", "gitlab": "GitLab", "ci/cd": "CI/CD",
    "linux": "Linux", "nginx": "Nginx", "prometheus": "Prometheus", "grafana": "Grafana",
    # data / ML
    "pandas": "Pandas", "numpy": "NumPy", "pytorch": "PyTorch",
    "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "spark": "Spark", "airflow": "Airflow", "dbt": "dbt", "hadoop": "Hadoop",
    "llm": "LLM", "tableau": "Tableau",
    # mobile / misc
    "android": "Android", "ios": "iOS", "flutter": "Flutter", "unity": "Unity",
    "git": "Git",
}
# Words that are also common English words: only match the exact casing.
_CASE_SENSITIVE = {"go": "Go", "swift": "Swift", "express": "Express", "spring": "Spring"}

_STACK_RE = re.compile(
    r"(?<![\w.])(?:"
    + "|".join(re.escape(k) for k in sorted(STACK_TERMS, key=len, reverse=True))
    + r")(?![\w])",
    re.I,
)


def _stack_matches(text: str) -> list[str]:
    found = []
    for m in _STACK_RE.finditer(text):
        word = m.group(0)
        key = word.lower()
        if key in _CASE_SENSITIVE and word != _CASE_SENSITIVE[key]:
            continue
        found.append(STACK_TERMS[key])
    return found


def extract_stack(text: str, tags: list[str] = ()) -> list[str]:
    result: list[str] = []
    candidates = [c for tag in tags for c in _stack_matches(tag)]
    candidates += _stack_matches(text or "")
    for name in candidates:
        if name not in result:
            result.append(name)
    return result


# ------------------------------------------------------------------ html

_BLOCKS = (
    "p div li ul ol br h1 h2 h3 h4 h5 h6 tr table section article pre blockquote hr"
).split()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    tree = HTMLParser(html)
    for node in tree.css("script, style"):
        node.decompose()
    for node in tree.css(", ".join(_BLOCKS)):
        node.insert_before("\n")
        node.insert_after("\n")
    body = tree.body
    text = body.text(deep=True, separator="") if body is not None else ""
    lines = (re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


# ------------------------------------------------------------- the whole

def normalize_job(job: Job) -> Job:
    if not job.description_text and job.description_html:
        job.description_text = html_to_text(job.description_html)
    if job.salary_min is None and job.salary_max is None and not job.salary_raw:
        job.salary_raw = salary_from_text(job.description_text)
    if job.salary_min is None and job.salary_max is None and job.salary_raw:
        sal = parse_salary(job.salary_raw)
        if sal:
            job.salary_min, job.salary_max = sal.min, sal.max
            job.salary_currency, job.salary_period = sal.currency, sal.period
    if not job.seniority:
        job.seniority = detect_seniority(job.title, job.description_text)
    job.stack = extract_stack(job.description_text, job.stack)
    return job
