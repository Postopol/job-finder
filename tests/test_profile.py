from datetime import UTC, datetime

import httpx
import pytest

from jobfinder import db, profile

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

RESUME = {
    "personalInfo": {"name": "Тест Тестов", "title": "Senior Backend Engineer", "email": "x@y.z"},
    "summary": "Backend engineer, Go and Python, event-driven systems on Kafka.",
    "workExperience": [
        {"title": "Senior Backend Engineer", "company": "A", "years": "Jan 2020 - Present",
         "description": ["Built services in Go on Kubernetes", "Moved billing to PostgreSQL"]},
        {"title": "Backend Engineer", "company": "B", "years": "Jun 2017 - Dec 2019",
         "description": ["Python, Django, Celery"]},
        {"title": "Intern", "company": "C", "years": "2018",  # overlaps, adds nothing
         "description": []},
    ],
    "skills": ["Go", "Python", "k8s", "Redis"],
    "languages": ["English (C1)", "Русский (родной)"],
}
LIST = [
    {"resume_id": "tailored", "filename": "t.pdf", "is_master": False, "is_default_master": False,
     "processing_status": "ready", "updated_at": "2026-11-21T10:00:00Z"},
    {"resume_id": "master", "filename": "my-cv.pdf", "is_master": True, "is_default_master": True,
     "processing_status": "ready", "updated_at": "2026-11-20T10:00:00Z"},
]


def transport(resumes=LIST, data=RESUME, status=200):
    def handler(req: httpx.Request):
        if status != 200:
            return httpx.Response(status)
        if req.url.path == "/api/v1/resumes":
            return httpx.Response(200, json={"data": resumes})
        rid = req.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={"data": {"resume_id": rid, "filename": "my-cv.pdf",
                                                  "processed_data": data}})
    return httpx.MockTransport(handler)


def test_build_profile():
    p = profile.build_profile(RESUME, NOW)
    assert p["title"] == "Senior Backend Engineer"
    assert p["roles"] == ["Senior Backend Engineer", "Backend Engineer", "Intern"]
    # resume skills first (synonyms unified), then technologies named in the text
    assert p["skills"][:4] == ["Go", "Python", "Kubernetes", "Redis"]
    assert {"PostgreSQL", "Django", "Kafka"} <= set(p["skills"])
    assert p["years"] == 9.4  # Jun 2017 – Nov 2026, the 2018 internship overlaps
    assert p["languages"] == ["English (C1)", "Русский (родной)"]
    assert "name" not in p and "email" not in str(p)  # personal details are not copied


@pytest.mark.parametrize("years,expected", [
    (["2019 – 2021"], 3.0), (["03.2022 - н.в."], 4.7), (["Сен 2021 — по настоящее время"], 5.2),
    (["since 2024"], 2.8), ([""], None), (["years of fun"], None),
])
def test_years_formats(years, expected):
    data = {"workExperience": [{"title": "Dev", "years": y} for y in years]}
    assert profile.build_profile(data, NOW)["years"] == expected


def test_refresh_stores_default_master(conn):
    snap = profile.refresh(conn, NOW, transport=transport())
    assert snap["resume_id"] == "master" and snap["filename"] == "my-cv.pdf"
    stored = db.get_setting(conn, "resume")
    assert stored["profile"]["title"] == "Senior Backend Engineer"
    assert stored["fetched_at"] == NOW.isoformat()


def test_refresh_flags_sample_resume(conn):
    sample = [{**LIST[1], "filename": "sample-resume.pdf"}]
    assert profile.refresh(conn, NOW, transport=transport(resumes=sample))["is_sample"] is True


def test_refresh_errors_keep_old_snapshot(conn):
    profile.refresh(conn, NOW, transport=transport())
    with pytest.raises(profile.ResumeUnavailable, match="не отвечает"):
        profile.refresh(conn, NOW, transport=httpx.MockTransport(
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))))
    with pytest.raises(profile.ResumeUnavailable, match="нет готового резюме"):
        profile.refresh(conn, NOW, transport=transport(resumes=[{**LIST[1], "processing_status": "failed"}]))
    with pytest.raises(profile.ResumeUnavailable, match="HTTP 500"):
        profile.refresh(conn, NOW, transport=transport(status=500))
    assert db.get_setting(conn, "resume")["resume_id"] == "master"


def test_refresh_quietly_never_raises(conn):
    assert profile.refresh_quietly(conn, NOW, transport=transport(status=500)) is False
    assert profile.refresh_quietly(conn, NOW, transport=transport()) is True
