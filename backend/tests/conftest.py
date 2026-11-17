"""Test configuration: an isolated temporary SQLite database. No network, no real orders."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="rt_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["DATA_DIR"] = _tmp
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    from app.db import run_migrations
    run_migrations()
    yield


@pytest.fixture
def session():
    from app.db import SessionLocal
    s = SessionLocal()
    try:
        yield s
        s.commit()
    finally:
        s.close()
