import pytest

from conftest import mk
from jobfinder.filters import FilterConfig, classify_scope, hidden_reason, is_non_it_title


@pytest.mark.parametrize("loc,desc,expected", [
    ("Anywhere in the World", "", "worldwide"),
    ("USA Only", "", "restricted"),
    ("Remote", "You must reside in the United States.", "restricted"),
    ("Удалённо", "Работа из любой точки СНГ", "cis"),
    ("Remote", "Join our global team", "worldwide"),
    ("Remote", "Nothing about location", "unknown"),
    ("Remote", "We need precise people", "unknown"),
])
def test_classify_scope_from_text(loc, desc, expected):
    assert classify_scope(mk(location_raw=loc, description_text=desc))[0] == expected


def test_structured_countries_respected():
    assert classify_scope(mk(countries=["KZ", "UZ"])) == ("cis", ["KZ", "UZ"])
    assert classify_scope(mk(countries=["US", "CA"])) == ("countries", ["US", "CA"])


@pytest.mark.parametrize("job,reason", [
    (dict(work_format="hybrid"), "hybrid"),
    (dict(location_raw="Berlin, on-site"), "office"),
    (dict(remote_scope="countries", countries=["US"]), "restricted"),
    (dict(remote_scope="countries", countries=["US", "KZ"]), None),
    (dict(title="Программист 1С"), "stopword:1с"),
    (dict(remote_scope="unknown"), None),
])
def test_hidden_reason(job, reason):
    assert hidden_reason(mk(**job), FilterConfig(country="KZ", stopwords=["1С"])) == reason


@pytest.mark.parametrize("loc,title,reason", [
    ("Гибридный формат", "Python", "hybrid"),
    ("Офис или удалёнка", "Python", None),
    ("Офис, Москва", "Python", "office"),
    ("работа в офисе", "Python", "office"),
    ("Berlin, on-site", "Python", "office"),
    ("Hybrid, remote days", "Python", "hybrid"),
    (None, "Hybrid Cloud Engineer", None),
    (None, "Senior Developer, hybrid mobile apps", None),
    (None, "Platform Engineer - hybrid in Warsaw", "hybrid"),
    (None, "Cloud Engineer (Hybrid)", "hybrid"),
    (None, "Инженер, гибридное облако", None),
    ("Hybrid cloud, 3 days in office", "Python", "hybrid"),
    ("Berlin, 2 days a week in the office", "Python", "hybrid"),
])
def test_format_words(loc, title, reason):
    assert hidden_reason(mk(location_raw=loc, title=title), FilterConfig()) == reason


def test_countries_scope_without_countries_is_unknown():
    j = mk(remote_scope="countries", location_raw="Remote", description_text="Nothing")
    assert classify_scope(j) == ("unknown", [])
    j = mk(remote_scope="countries", description_text="worldwide team")
    assert classify_scope(j)[0] == "worldwide"


def test_hidden_countries_scope_empty_countries_not_hidden():
    j = mk(remote_scope="countries", countries=[], location_raw="Remote", title="Python")
    assert hidden_reason(j, FilterConfig()) is None


@pytest.mark.parametrize("title,expected", [
    ("Senior Sales Engineer", True), ("Customer Success Engineer", True),
    ("Backend Engineer", False), ("Data Engineer", False),
    ("Technical Support Engineer", True), ("Art Director", True),
    ("Python Developer", False),
])
def test_is_non_it_title(title, expected):
    assert is_non_it_title(title) is expected


def test_hidden_reason_non_it_before_restricted_and_stopwords():
    cfg = FilterConfig(stopwords=["accountant"])
    assert hidden_reason(mk(title="Staff Accountant"), cfg) == "non_it"
    assert hidden_reason(mk(title="Staff Accountant", remote_scope="restricted"), cfg) == "non_it"
    assert hidden_reason(mk(title="Staff Accountant", work_format="hybrid"), cfg) == "hybrid"
    assert hidden_reason(mk(title="Backend Engineer"), FilterConfig()) is None


@pytest.mark.parametrize("title", [
    "Medical Software Engineer", "Finance Software Engineer", "Legal Tech Backend Engineer",
    "Marketing Tech Engineer", "HR Tech Full Stack Developer", "Clinical Data Engineer",
    "AI Tutor - Software Engineering", "IT Operations Manager",
    "Site Reliability Operations Manager", "Accounting Software Engineer",
    "Talent Platform Engineer", "Support Engineer (Linux kernel)"])
def test_domain_word_with_it_noun_stays_it(title):
    assert is_non_it_title(title) is False


@pytest.mark.parametrize("title", [
    "Senior Sales Engineer", "Customer Success Engineer", "PreSales Solutions Engineer",
    "Staff Accountant", "Operations Manager", "Medical Billing Specialist"])
def test_role_words_always_non_it(title):
    assert is_non_it_title(title) is True


def _country_reason(countries=None, desc=""):
    """Scope and hide reason the collector computes for a job (KZ user)."""
    j = mk(remote_scope="countries" if countries else "unknown", countries=countries or [],
           location_raw="Remote", description_text=desc)
    j.remote_scope, j.countries = classify_scope(j, "KZ")
    return j.remote_scope, hidden_reason(j, FilterConfig(country="KZ"))


@pytest.mark.parametrize("countries,desc,scope,reason", [
    (["RU"], "", "countries", "restricted"),            # Russia only: not available from KZ
    (["RU", "BY"], "", "countries", "restricted"),      # CIS countries without KZ
    (["KZ", "RU"], "", "cis", None),
    (["KZ"], "", "cis", None),
    (["US", "KZ"], "", "countries", None),
    (["US"], "", "countries", "restricted"),
    (None, "Работа из любой точки СНГ", "cis", None),  # text-detected «СНГ» stays visible
])
def test_country_list_must_contain_user_country(countries, desc, scope, reason):
    assert _country_reason(countries, desc) == (scope, reason)


def test_user_country_in_list_whatever_the_scope():
    cfg = FilterConfig(country="KZ")
    assert hidden_reason(mk(remote_scope="cis", countries=["RU"]), cfg) == "restricted"
    assert hidden_reason(mk(remote_scope="worldwide", countries=["RU"]), cfg) == "restricted"
    # «СНГ» for a list depends on the user's country
    assert classify_scope(mk(countries=["RU"]), "RU") == ("cis", ["RU"])
    assert classify_scope(mk(countries=["RU"]), "KZ") == ("countries", ["RU"])


@pytest.mark.parametrize("title,expected", [
    ("Менеджер по продажам", True), ("Маркетолог", True), ("Бухгалтер", True),
    ("Рекрутер в IT", True), ("Менеджер по работе с клиентами", True),
    ("Менеджер по развитию бизнеса (Сибирь)", True), ("Директор по продажам", True),
    ("Python-разработчик", False), ("Разработчик CRM для отдела продаж", False),
    ("Программист платформы продаж", False), ("Аналитик данных", False),
    ("Системный аналитик", False), ("Тестировщик", False),
    ("Системный аналитик (CRM, продажи)", False), ("Аналитик BI продаж", False),
])
def test_non_it_russian_titles(title, expected):
    assert is_non_it_title(title) is expected


@pytest.mark.parametrize("loc,scope", [
    ("REMOTE (US)", "restricted"), ("√ REMOTE (US)", "restricted"),
    ("REMOTE (US & US Citizen)", "restricted"), ("Remote - Europe", "restricted"),
    ("REMOTE (UK)", "restricted"), ("LATAM", "restricted"), ("North America", "restricted"),
    ("Europe, LATAM, APAC, the U.S., Canada", "restricted"), ("REMOTE (Brazil)", "restricted"),
    ("Remote", "unknown"), ("REMOTE or ONSITE", "unknown"), ("Москва", "unknown"),
    ("Remote (EMEA)", "unknown"), ("Remote (Asia)", "unknown"), ("Full-time", "unknown"),
    ("Remote (US, Kazakhstan)", "cis"), ("Remote (Worldwide)", "worldwide"),
    ("Remote (CIS)", "cis"), ("Remote or onsite (US + many countries)", "unknown"),
])
def test_region_limited_remote_is_restricted(loc, scope):
    assert classify_scope(mk(location_raw=loc, remote_scope="unknown"), "KZ")[0] == scope
