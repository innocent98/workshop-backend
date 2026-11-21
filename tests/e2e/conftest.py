"""
Live smoke tests (marker ``e2e``) run by cd-staging.yml against a freshly deployed staging
stack. They talk to ``E2E_BASE_URL`` over HTTP; there is no database or app import involved.

The parent ``tests/conftest.py`` has autouse fixtures that connect to the unit-test database
and truncate every table. The two fixtures below shadow them (same names, nearer conftest) so
that an e2e run neither needs a database nor can ever touch one.
"""

import os

import httpx
import pytest


@pytest.fixture(scope="session", autouse=True)
def _schema():  # noqa: D401 - shadows tests/conftest.py::_schema on purpose
    """No database for live smoke tests."""
    yield


@pytest.fixture(autouse=True)
def _clean_tables(_schema):  # noqa: D401 - shadows tests/conftest.py::_clean_tables
    """Never truncate anything from a live smoke test."""
    yield


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("E2E_BASE_URL", "").strip().rstrip("/")
    if not url:
        pytest.skip("E2E_BASE_URL is not set (live smoke tests run from cd-staging.yml)")
    return url


@pytest.fixture(scope="session")
def live(base_url: str):
    timeout = float(os.environ.get("E2E_TIMEOUT_SECONDS", "60"))
    with httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=False) as client:
        yield client
