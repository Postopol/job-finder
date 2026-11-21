import pytest

from conftest import mk
from jobfinder.filters import FilterConfig, classify_scope, hidden_reason


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
