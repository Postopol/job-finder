from datetime import datetime, timezone

import pytest

from jobfinder.db import connect
from jobfinder.models import Job


def mk(**kw) -> Job:
    base = dict(source="s1", source_id="1", url="https://x/1",
                title="Python Developer", company="Acme")
    base.update(kw)
    return Job(**base)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "j.db")
    yield c
    c.close()


@pytest.fixture
def now():
    return datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
