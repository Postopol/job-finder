"""Keyboard control: the script is on every page, list items carry their id, buttons show keys."""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from jobfinder.db import connect, upsert_job
from jobfinder.web.app import create_app
from tests.conftest import mk


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "j.db", start_scheduler=False, extra_hosts=("testserver",))
    with TestClient(app) as c:
        c.db_path = tmp_path / "j.db"
        yield c


def seed(path, **kw):
    conn = connect(path)
    try:
        jid, _ = upsert_job(conn, mk(**kw), None, datetime.now(UTC))
    finally:
        conn.close()
    return jid


@pytest.mark.parametrize("url", ["/", "/triage", "/sources"])
def test_keys_script_loaded_once(client, url):
    html = client.get(url).text
    assert html.count("/static/keys.js") == 1 and "/static/keys.css" in html


def test_list_items_carry_job_id(client):
    jid = seed(client.db_path)
    assert f'data-job-id="{jid}"' in client.get("/?fresh=all").text


def test_status_buttons_show_keys(client):
    jid = seed(client.db_path)
    html = client.get(f"/jobs/{jid}").text
    assert 'aria-keyshortcuts="ArrowRight"' in html and 'aria-keyshortcuts="ArrowLeft"' in html
    assert "<kbd>A</kbd>" in html


def test_static_files_served(client):
    js = client.get("/static/keys.js")
    assert js.status_code == 200 and "KeyJ" in js.text
    assert client.get("/static/keys.css").status_code == 200
