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
