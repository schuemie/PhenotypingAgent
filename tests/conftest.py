from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolated_environment():
    """Snapshot and restore ``os.environ`` around every test.

    ``tests/test_llm_config.py`` deliberately sets provider/tier variables. Without isolation
    those leak into later tests and make the fixture-backed dry run try to reach a real LLM
    provider, which is exactly the failure mode this fixture prevents.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)

