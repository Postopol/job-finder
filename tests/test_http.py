import httpx
import pytest

from jobfinder.http import PoliteClient, SourceBlocked, SourceError
from jobfinder.models import Job
from jobfinder.sources import base
from jobfinder.sources.base import ParseError


def make(handler, **kw):
    sleeps = []
    c = PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    return c, sleeps


def test_429_raises_blocked_without_retry():
    calls = []

    def h(req):
        calls.append(req)
        return httpx.Response(429)

    c, _ = make(h)
    with pytest.raises(SourceBlocked) as e:
        c.get("https://x/")
    assert e.value.status == 429 and "429" in str(e.value)
    assert len(calls) == 1
    assert c.blocked == 429


def test_5xx_retries_then_source_error():
    calls = []

    def h(req):
        calls.append(req)
        return httpx.Response(500)

    c, sleeps = make(h)
    with pytest.raises(SourceError):
        c.get("https://x/")
    assert len(calls) == 3 and c.requests == 3
    assert sleeps == [1, 2]


def test_404_no_retry():
    calls = []

    def h(req):
        calls.append(req)
        return httpx.Response(404)

    c, _ = make(h)
    with pytest.raises(SourceError):
        c.get("https://x/")
    assert len(calls) == 1


def test_delay_between_requests():
    c, sleeps = make(lambda r: httpx.Response(200))
    c.get("https://x/")
    assert sleeps == []
    c.get("https://x/")
    assert len(sleeps) == 1 and 1.0 <= sleeps[0] <= 2.0


def test_user_agent_has_no_email_and_header_merge():
    seen = []

    def h(req):
        seen.append(req.headers)
        return httpx.Response(200)

    c, _ = make(h)
    c.get("https://x/", headers={"Authorization": "Bearer t"})
    assert "@" not in seen[0]["user-agent"]
    assert seen[0]["user-agent"].startswith("Mozilla/5.0 (X11; Linux x86_64; rv:130.0)")
    assert seen[0]["authorization"] == "Bearer t"


def j(i):
    return Job(source="s", source_id=i, url="u", title="t")


def test_paged_stops_at_known():
    pages = {1: [{"id": "a"}, {"id": "b"}], 2: [{"id": "c"}, {"id": "known"}], 3: [{"id": "d"}]}
    asked = []

    def fetch(n):
        asked.append(n)
        return pages[n]

    out = base.paged(fetch, lambda it: j(it["id"]), {"known"}, 5)
    assert [x.source_id for x in out] == ["a", "b", "c", "known"]
    assert asked == [1, 2]


def test_paged_empty_and_max_and_none():
    out = base.paged(lambda n: [{"id": "a"}, {"id": "x"}] if n < 10 else [],
                     lambda it: None if it["id"] == "x" else j(it["id"]), set(), 3)
    assert len(out) == 3
    assert base.paged(lambda n: [], lambda it: j("a"), set(), 3) == []


def test_next_data_missing_raises_parse_error():
    with pytest.raises(ParseError, match="формат страницы изменился"):
        base.next_data("<html></html>")


def test_next_data_ok_and_invalid():
    html = '<script id="__NEXT_DATA__" type="application/json">{"a": 1}</script>'
    assert base.next_data(html) == {"a": 1}
    with pytest.raises(ParseError, match="формат страницы изменился"):
        base.next_data('<script id="__NEXT_DATA__">{oops</script>')


def test_nuxt_data_revives_references():
    html = '<script id="__NUXT_DATA__">[{"a":1},["Reactive",2],{"b":3},"x"]</script>'
    assert base.nuxt_data(html) == {"a": {"b": "x"}}


def test_nuxt_data_negative_none_and_cycle():
    html = '<script id="__NUXT_DATA__">[{"a":-1,"b":-2,"c":0}]</script>'
    r = base.nuxt_data(html)
    assert r["a"] is None and r["b"] is None and r["c"] is r
    with pytest.raises(ParseError):
        base.nuxt_data("<html></html>")


def _job(sid):
    return Job(source="s", source_id=sid, url=f"https://x/{sid}", title=f"Dev {sid}")


def test_describe_new_stops_on_block_and_defers_undescribed():
    jobs = [_job("a"), _job("known"), _job("b"), _job("hidden"), _job("c")]
    described = []

    def describe(job):
        if len(described) == 1:
            raise SourceBlocked(429)
        described.append(job.source_id)
        job.description_text = "full"

    out = base.describe_new(jobs, {"known"}, lambda j: j.source_id != "hidden", describe, "s")
    # "a" described, "known" and filtered-out "hidden" kept, "b"/"c" left for the next run
    assert [j.source_id for j in out] == ["a", "known", "hidden"]
    assert described == ["a"]


def test_describe_new_describes_only_new_wanted():
    jobs = [_job("a"), _job("known"), _job("hidden")]
    seen = []
    out = base.describe_new(jobs, {"known"}, lambda j: j.source_id != "hidden",
                            lambda j: seen.append(j.source_id), "s")
    assert out == jobs and seen == ["a"]
