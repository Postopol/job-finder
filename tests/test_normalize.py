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


@pytest.mark.parametrize("title,text,expected", [
    ("Software Engineer", "We need 5+ years of experience with Python.", "senior"),
    ("Data Engineer", "3+ years of professional experience", "middle"),
    ("Data Engineer", "Requirements: 2-4 years of hands-on experience", "middle"),
    ("QA Engineer", "1+ year of experience in testing", "junior"),
    ("QA Engineer", "Experience: 6 years in backend", "senior"),
    ("Backend Developer", "minimum 4 years experience", "senior"),
    ("Go-разработчик", "Опыт работы от 3 лет", "middle"),
    ("Python-разработчик", "Опыт коммерческой разработки не менее 5 лет", "senior"),
    ("Аналитик", "3+ года опыта в аналитике", "middle"),
    ("ML-инженер", "Опыт от 1 года", "junior"),
    # several mentions: the largest requirement wins
    ("SRE", "3+ years of Linux experience, 1+ year of Kubernetes experience", "middle"),
    # years of the company, not of experience
    ("Developer", "Our company has 10 years on the market", None),
    # years beat level words in the text ("work with senior engineers")
    ("Developer", "You will work with senior engineers. 2+ years of experience", "middle"),
    # the title still wins
    ("Junior Developer", "5+ years of experience", "junior"),
    ("Director of Engineering", "", "lead"),
    ("Engineering Manager", "", "lead"),
    ("Директор по разработке", "", "lead"),
])
def test_detect_seniority_from_experience(title, text, expected):
    assert detect_seniority(title, text) == expected


# ---- salary hidden in the description text

from jobfinder.models import Job  # noqa: E402
from jobfinder.normalize import normalize_job, salary_from_text  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("Salary Range: $85,389 - $116,975 If you have previously applied", (85389, 116975, "USD", "year")),
    ("The annual base salary range for this full-time position is $75,000 to $115,000.",
     (75000, 115000, "USD", "year")),
    ("expected to be between $121,800 and $162,400 per year.", (121800, 162400, "USD", "year")),
    ("$150K to $240K base plus equity.", (150000, 240000, "USD", "year")),
    ("| Full-time | $110K–$140K + equity |", (110000, 140000, "USD", "year")),
    ("We offer a pay range of $70 - $100per hour, with the exact rate", (70, 100, "USD", "hour")),
    ("Pay: $60–$120/hour Location: Global", (60, 120, "USD", "hour")),
    ("Salary range for this position is $95,000.00 - $120,000.00 per year annually.",
     (95000, 120000, "USD", "year")),
    ("Chief Operating Officer, $180–250k - Director", (180000, 250000, "USD", "year")),
    ("Compensation: €4,000 per month", (4000, None, "EUR", "month")),
])
def test_salary_from_text(text, expected):
    sal = parse_salary(salary_from_text(text))
    assert (sal.min, sal.max, sal.currency, sal.period) == expected


@pytest.mark.parametrize("text", [
    "receive a monthly home internet reimbursement, and $500 USD to customize your workstation",
    "Grow your career with $1500 USD annually for professional development",
    "GPS will contribute ($850 per EE annually / $1750 per family annually",
    "We raised $10M from top investors and process $10 billion a year",
    "We offer a pay range of $6 to $9 with flexible hours",  # no unit, too small for a month
    "No numbers here at all",
    "",
])
def test_salary_from_text_ignores_non_salary_money(text):
    assert parse_salary(salary_from_text(text)) is None


def test_normalize_fills_salary_from_description():
    job = normalize_job(Job(source="s", source_id="1", url="u", title="Engineer",
                            description_text="Benefits. Salary Range: $85,000 - $100,000"))
    assert (job.salary_min, job.salary_max, job.salary_currency) == (85000, 100000, "USD")
    assert job.salary_raw == "$85,000 - $100,000"

    given = normalize_job(Job(source="s", source_id="2", url="u", title="Engineer",
                              salary_raw="$5,000 per month",
                              description_text="Salary Range: $85,000 - $100,000"))
    assert given.salary_min == 5000  # the source's own salary wins


def test_salary_from_text_is_fast_on_hostile_text():
    import time
    start = time.monotonic()
    for text in ("$" + "1," * 20000 + "x", "$1 - " * 5000, "$" + "1" * 9000 + " to $" + "1," * 5000):
        salary_from_text(text)
    assert time.monotonic() - start < 1.0
