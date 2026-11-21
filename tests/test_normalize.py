import pytest
from jobfinder.normalize import parse_salary, detect_seniority, extract_stack, html_to_text, Salary

@pytest.mark.parametrize("text,expected", [
    ("от 300 000 ₽", Salary(300000, None, "RUB", "month")),
    ("до 200 тыс. руб.", Salary(None, 200000, "RUB", "month")),
    ("350 000–450 000 ₽", Salary(350000, 450000, "RUB", "month")),
    ("$70k–90k", Salary(70000, 90000, "USD", "year")),
    ("$5,000 - $6,500 / month", Salary(5000, 6500, "USD", "month")),
    ("€3,500 - 4,500 per month", Salary(3500, 4500, "EUR", "month")),
    ("$45/hr", Salary(45, None, "USD", "hour")),
    ("500 000 ₸", Salary(500000, None, "KZT", "month")),
])
def test_parse_salary(text, expected):
    assert parse_salary(text) == expected

@pytest.mark.parametrize("text", ["competitive", "", None, "по договорённости", "💰💰"])
def test_parse_salary_unparseable_returns_none(text):
    assert parse_salary(text) is None

def test_period_defaults():
    # bare USD amount >= 20000 is yearly, below is monthly; RUB/KZT default monthly
    assert parse_salary("$120,000").period == "year"
    assert parse_salary("$4000").period == "month"

@pytest.mark.parametrize("title,expected", [
    ("Senior Python Developer", "senior"), ("Старший разработчик", "senior"),
    ("Ведущий инженер", "senior"), ("Middle+ Go-разработчик", "middle"),
    ("Junior QA", "junior"), ("Team Lead Backend", "lead"), ("Developer", None),
])
def test_detect_seniority(title, expected):
    assert detect_seniority(title) == expected

def test_extract_stack_aliases_and_symbols():
    text = "We use golang, k8s, Postgres, C++, C# and .NET; Node.js is a plus"
    assert extract_stack(text) == ["Go", "Kubernetes", "PostgreSQL", "C++", "C#", ".NET", "Node.js"]

def test_extract_stack_whole_words_only():
    assert "Go" not in extract_stack("Good communication, Django")
    assert extract_stack("Django") == ["Django"]

def test_html_to_text_strips_tags_and_keeps_breaks():
    assert html_to_text("<p>One</p><ul><li>Two</li></ul><script>x()</script>") == "One\nTwo"


def test_period_words_need_word_start():
    assert parse_salary("частичная занятость 50000 ₽") == Salary(50000, None, "RUB", "month")
    assert parse_salary("100 000 ₽ в месяц").period == "month"
    assert parse_salary("1500 ₽ в час").period == "hour"


def _job(**kw):
    from jobfinder.models import Job
    return Job(source="s", source_id="1", url="u", title=kw.pop("title", "Developer"), **kw)


def test_normalize_job_fills_fields():
    from jobfinder.normalize import normalize_job
    job = normalize_job(_job(title="Senior Dev", description_html="<p>Python and Go</p>",
                             salary_raw="$5,000 - $6,500 / month", stack=["python", "k8s", "remote"]))
    assert job.description_text == "Python and Go"
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (5000, 6500, "USD", "month")
    assert job.seniority == "senior"
    assert job.stack == ["Python", "Kubernetes", "Go"]


def test_normalize_job_keeps_existing_values():
    from jobfinder.normalize import normalize_job
    job = normalize_job(_job(title="Senior Dev", description_html="<p>x</p>", description_text="given",
                             salary_raw="$1,000", salary_min=1, seniority="lead"))
    assert job.description_text == "given"
    assert job.salary_min == 1 and job.salary_max is None and job.salary_currency is None
    assert job.seniority == "lead"


@pytest.mark.parametrize("text,period", [
    ("почасовая оплата 1500 ₽", "hour"),
    ("часовая ставка 1500 ₽", "hour"),
    ("годовой оклад 3000000 ₽", "year"),
    ("месячный доход 100000 ₽", "month"),
    ("помесячно 100000 ₽", "month"),
    ("частичная занятость 50000 ₽", "month"),
    ("часто 50000 ₽, часть времени", "month"),
])
def test_russian_period_forms(text, period):
    assert parse_salary(text).period == period
