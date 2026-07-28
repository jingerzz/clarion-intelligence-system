"""Shared test fixtures.

Unit tests must be hermetic: on a live Zo deployment, ZO_API_KEY /
ZO_CLIENT_IDENTITY_TOKEN are present in the environment, and any code path
that constructs a ZoClient from env (e.g. search()'s weak-query escalation)
would silently make REAL /zo/ask calls from inside unit tests. Strip the
tokens for every test — tests that need an LLM pass a fake client explicitly.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_zo_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    monkeypatch.delenv("ZO_CLIENT_IDENTITY_TOKEN", raising=False)
