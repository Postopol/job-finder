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
