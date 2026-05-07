"""Smoke tests for ai_buffett_zo.llm.zo_client.

No live HTTP — _post_json and _token are monkeypatched so tests run fully offline.
"""

from __future__ import annotations

import pytest

from ai_buffett_zo.llm import (
    AskResult,
    Repair,
    ZoAuthError,
    ZoClient,
    ZoSchemaError,
    as_int,
    schemas,
)
from ai_buffett_zo.llm.zo_client import _shape_check, _validate_schema


# ---- Schema validation ------------------------------------------------------


def test_validate_schema_rejects_integer_at_top_level() -> None:
    with pytest.raises(ZoSchemaError, match="integer"):
        _validate_schema({"type": "integer"})


def test_validate_schema_rejects_integer_in_property() -> None:
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    with pytest.raises(ZoSchemaError, match=r"\$.count"):
        _validate_schema(schema)


def test_validate_schema_rejects_integer_in_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {"counts": {"type": "array", "items": {"type": "integer"}}},
    }
    with pytest.raises(ZoSchemaError):
        _validate_schema(schema)


def test_validate_schema_accepts_known_section_summary() -> None:
    _validate_schema(schemas.SECTION_SUMMARY_SCHEMA)


# ---- Shape check ------------------------------------------------------------


def test_shape_check_passes_complete_object() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    }
    assert _shape_check({"a": "hi", "b": 3.0}, schema) == []


def test_shape_check_flags_missing_required() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    }
    problems = _shape_check({"a": "hi"}, schema)
    assert problems == ["missing:b"]


def test_shape_check_flags_wrong_type() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    }
    problems = _shape_check({"a": 42}, schema)
    assert problems == ["wrongtype:a (want string)"]


# ---- Repair pass ------------------------------------------------------------


def test_repair_aliases_and_defaults() -> None:
    r = Repair(
        aliases={"summary": "one_sentence_summary"},
        defaults={"one_sentence_summary": "", "key_points": []},
    )
    out = r.apply({"summary": "hi"})
    assert out == {"one_sentence_summary": "hi", "key_points": []}


def test_repair_handles_non_dict_with_defaults() -> None:
    r = Repair(defaults={"x": 0})
    assert r.apply(None) == {"x": 0}
    assert r.apply("oops") == {"x": 0}


def test_section_summary_repair_normalizes_minimax_quirks() -> None:
    raw = {
        "summary": "Supplier risk",
        "bullets": ["a", "b"],
        "tags": ["geopolitical"],
        "risk_level": 4.0,
        "tickers": ["NVDA"],
    }
    out = schemas.SECTION_SUMMARY_REPAIR.apply(raw)
    assert out["one_sentence_summary"] == "Supplier risk"
    assert out["key_points"] == ["a", "b"]
    assert out["themes"] == ["geopolitical"]
    assert out["severity"] == 4.0
    assert out["tickers_or_entities"] == ["NVDA"]


# ---- as_int ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3.0, 3),
        (3.4, 3),
        (3.6, 4),
        (3, 3),
        ("4", 4),
        (None, 0),
        ("", 0),
    ],
)
def test_as_int(value: object, expected: int) -> None:
    assert as_int(value) == expected


# ---- ZoClient.ask (mocked) -------------------------------------------------


def _make_client(monkeypatch: pytest.MonkeyPatch, response: dict) -> ZoClient:
    """Construct a client with token + _post_json monkeypatched to return `response`."""
    client = ZoClient(token="zo_sk_test")
    monkeypatch.setattr(
        client,
        "_post_json",
        lambda url, payload: response,  # type: ignore[arg-type]
    )
    return client


def test_ask_freeform_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(
        monkeypatch,
        {"output": "KO has a durable brand and distribution moat.", "conversation_id": "c1"},
    )
    result = client.ask("Describe KO's moat in one sentence.")
    assert isinstance(result, AskResult)
    assert result.ok is True
    assert "KO" in result.data
    assert result.conversation_id == "c1"


def test_ask_with_schema_applies_repair_and_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(
        monkeypatch,
        {
            "output": {
                "summary": "Supplier risk",
                "bullets": ["a"],
                "tags": ["geopolitical"],
                "risk_level": 3,
                "tickers": ["NVDA"],
            },
        },
    )
    result = client.ask(
        "summarize",
        output_format=schemas.SECTION_SUMMARY_SCHEMA,
        repair=schemas.SECTION_SUMMARY_REPAIR,
    )
    assert result.ok, result.problems
    assert result.data["one_sentence_summary"] == "Supplier risk"
    assert as_int(result.data["severity"]) == 3


def test_ask_with_schema_flags_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch, {"output": {"summary": "hi"}})
    # No repair provided — empty raw object yields all-missing
    result = client.ask(
        "summarize",
        output_format=schemas.SECTION_SUMMARY_SCHEMA,
    )
    assert not result.ok
    assert any(p.startswith("missing:") for p in result.problems)


def test_ask_rejects_integer_schema_at_compose_time() -> None:
    client = ZoClient(token="zo_sk_test")
    with pytest.raises(ZoSchemaError):
        client.ask(
            "irrelevant",
            output_format={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        )


# ---- Token resolution ------------------------------------------------------


def test_no_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    monkeypatch.delenv("ZO_CLIENT_IDENTITY_TOKEN", raising=False)
    client = ZoClient()
    with pytest.raises(ZoAuthError):
        client._token()


def test_zo_api_key_takes_precedence_over_identity_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_explicit")
    monkeypatch.setenv("ZO_CLIENT_IDENTITY_TOKEN", "zo_identity_fallback")
    client = ZoClient()
    assert client._token() == "zo_sk_explicit"


def test_explicit_token_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_env")
    client = ZoClient(token="zo_sk_arg")
    assert client._token() == "zo_sk_arg"
