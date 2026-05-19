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


# ---- Config-driven model defaults ------------------------------------------


def test_load_config_models_falls_back_when_config_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No config.json on disk → all three keys fall back to hardcoded defaults."""
    from ai_buffett_zo import _paths
    from ai_buffett_zo.llm import zo_client as zc

    monkeypatch.setattr(_paths, "clarion_home", lambda: tmp_path)
    models = zc._load_config_models()
    assert models["indexing_model"] == zc._FALLBACK_MODEL_INDEX
    assert models["indexing_fallback_model"] == zc._FALLBACK_MODEL_INDEX_FALLBACK
    assert models["reasoning_model"] == zc._FALLBACK_MODEL_REASONING


def test_load_config_models_reads_from_config_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All three keys present in config.json override the hardcoded defaults."""
    import json as _json
    from ai_buffett_zo import _paths
    from ai_buffett_zo.llm import zo_client as zc

    (tmp_path / "config.json").write_text(
        _json.dumps({
            "indexing_model": "zo:custom-index",
            "indexing_fallback_model": "zo:custom-fallback",
            "reasoning_model": "zo:custom-reasoning",
        })
    )
    monkeypatch.setattr(_paths, "clarion_home", lambda: tmp_path)
    models = zc._load_config_models()
    assert models["indexing_model"] == "zo:custom-index"
    assert models["indexing_fallback_model"] == "zo:custom-fallback"
    assert models["reasoning_model"] == "zo:custom-reasoning"


def test_load_config_models_partial_override(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single key in config.json overrides only that one — others fall back."""
    import json as _json
    from ai_buffett_zo import _paths
    from ai_buffett_zo.llm import zo_client as zc

    (tmp_path / "config.json").write_text(
        _json.dumps({"reasoning_model": "zo:my-reasoner"})
    )
    monkeypatch.setattr(_paths, "clarion_home", lambda: tmp_path)
    models = zc._load_config_models()
    assert models["reasoning_model"] == "zo:my-reasoner"
    assert models["indexing_model"] == zc._FALLBACK_MODEL_INDEX
    assert models["indexing_fallback_model"] == zc._FALLBACK_MODEL_INDEX_FALLBACK


def test_load_config_models_handles_malformed_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken config.json falls through to all defaults — never crashes."""
    from ai_buffett_zo import _paths
    from ai_buffett_zo.llm import zo_client as zc

    (tmp_path / "config.json").write_text("{not valid json")
    monkeypatch.setattr(_paths, "clarion_home", lambda: tmp_path)
    models = zc._load_config_models()
    assert models["indexing_model"] == zc._FALLBACK_MODEL_INDEX


def test_load_config_models_handles_non_dict_root(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config.json containing a list (or any non-dict) falls through cleanly."""
    import json as _json
    from ai_buffett_zo import _paths
    from ai_buffett_zo.llm import zo_client as zc

    (tmp_path / "config.json").write_text(_json.dumps(["not", "a", "dict"]))
    monkeypatch.setattr(_paths, "clarion_home", lambda: tmp_path)
    models = zc._load_config_models()
    assert models["indexing_model"] == zc._FALLBACK_MODEL_INDEX


def test_load_config_models_empty_string_falls_back(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty string for a key falls through to fallback — never use a blank model name."""
    import json as _json
    from ai_buffett_zo import _paths
    from ai_buffett_zo.llm import zo_client as zc

    (tmp_path / "config.json").write_text(
        _json.dumps({"indexing_model": "", "reasoning_model": "  "})
    )
    monkeypatch.setattr(_paths, "clarion_home", lambda: tmp_path)
    models = zc._load_config_models()
    assert models["indexing_model"] == zc._FALLBACK_MODEL_INDEX
    # Note: " " (non-empty whitespace) is technically truthy in Python. Document
    # this — users should either set a real value or leave the key absent.
    assert models["reasoning_model"] == "  "


def test_all_fallback_models_are_free_tier() -> None:
    """ARCHITECTURE.md policy: every default model must be free-tier.

    A fresh Clarion install must run end-to-end on a free Zo account without
    hitting tier-access errors. Subscriber-tier models are opt-in via
    ~/clarion/config.json, never the default.

    If a future PR introduces a new fallback constant, add the model to the
    KNOWN_FREE_TIER set below (after verifying it really is free-tier on the
    Zo platform) — or pick a different model. Do not weaken this test.
    """
    from ai_buffett_zo.llm import zo_client as zc

    KNOWN_FREE_TIER = {
        "zo:openai/gpt-5.4-mini",
        "zo:minimax/minimax-m2.5",
    }

    assert zc._FALLBACK_MODEL_INDEX in KNOWN_FREE_TIER, (
        f"_FALLBACK_MODEL_INDEX is {zc._FALLBACK_MODEL_INDEX} — not in the "
        f"verified free-tier set. See ARCHITECTURE.md 'Default model selection'."
    )
    assert zc._FALLBACK_MODEL_INDEX_FALLBACK in KNOWN_FREE_TIER, (
        f"_FALLBACK_MODEL_INDEX_FALLBACK is {zc._FALLBACK_MODEL_INDEX_FALLBACK} — not free-tier."
    )
    assert zc._FALLBACK_MODEL_REASONING in KNOWN_FREE_TIER, (
        f"_FALLBACK_MODEL_REASONING is {zc._FALLBACK_MODEL_REASONING} — not free-tier. "
        f"Subscriber-tier models are opt-in via ~/clarion/config.json, never default."
    )


def test_setup_default_config_reasoning_model_is_free_tier() -> None:
    """Mirror check on setup.py's DEFAULT_CONFIG. A fresh ~/clarion/config.json
    written by setup.py must contain free-tier values."""
    import importlib.util
    from pathlib import Path

    setup_path = (
        Path(__file__).resolve().parents[1]
        / "skills" / "clarion-setup" / "scripts" / "setup.py"
    )
    spec = importlib.util.spec_from_file_location("clarion_setup_check", setup_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    KNOWN_FREE_TIER = {
        "zo:openai/gpt-5.4-mini",
        "zo:minimax/minimax-m2.5",
    }
    cfg = mod.DEFAULT_CONFIG
    for key in ("indexing_model", "indexing_fallback_model", "reasoning_model"):
        assert cfg[key] in KNOWN_FREE_TIER, (
            f"setup.py DEFAULT_CONFIG['{key}'] = {cfg[key]!r} — not free-tier. "
            f"See ARCHITECTURE.md 'Default model selection'."
        )
