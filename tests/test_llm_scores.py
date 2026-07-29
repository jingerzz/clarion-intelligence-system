"""Tests for ai_buffett_zo.theses.llm_scores.

The real-money invariant under test: on ANY failure (no token, network
error, unparseable response, missing component), failed components are
OMITTED — never zero-filled — so the monitor carries forward previous
scores instead of cratering the Overall score with fabricated zeros.
"""

from __future__ import annotations

import json

import pytest

from ai_buffett_zo.theses import llm_scores
from ai_buffett_zo.theses.llm_scores import (
    _parse_scores,
    score_thesis_with_llm,
)

GOOD_RESPONSE = json.dumps(
    {
        "business_health": {"score": 82, "notes": "Revenue accelerating."},
        "insider_alignment": {"score": 55, "notes": "Neutral Form 4 activity."},
        "thesis_integrity": {"score": 74, "notes": "Claims hold; evidence current."},
    }
)


def _score(**kwargs):
    defaults = dict(
        ticker="NVDA",
        thesis_markdown="# Thesis\n\nBody.",
        current_price=100.0,
        base_case_fair_value=120.0,
    )
    defaults.update(kwargs)
    return score_thesis_with_llm(**defaults)


# ---- parsing ---------------------------------------------------------------


def test_parse_bare_json():
    out = _parse_scores(GOOD_RESPONSE, ticker="NVDA")
    assert set(out) == {"Business Health", "Insider Alignment", "Thesis Integrity"}
    assert out["Business Health"].score == 82
    assert out["Business Health"].weight == 20
    assert out["Insider Alignment"].score == 55
    assert out["Thesis Integrity"].score == 74
    assert "accelerating" in out["Business Health"].notes.lower()


def test_parse_fenced_json():
    fenced = f"```json\n{GOOD_RESPONSE}\n```"
    out = _parse_scores(fenced, ticker="NVDA")
    assert len(out) == 3
    assert out["Thesis Integrity"].score == 74


def test_parse_json_embedded_in_prose():
    wrapped = f"Here are the scores you asked for:\n\n{GOOD_RESPONSE}\n\nLet me know."
    out = _parse_scores(wrapped, ticker="NVDA")
    assert len(out) == 3


def test_parse_garbage_returns_empty():
    assert _parse_scores("I could not score this thesis.", ticker="NVDA") == {}
    assert _parse_scores("", ticker="NVDA") == {}
    assert _parse_scores("[1, 2, 3]", ticker="NVDA") == {}


def test_parse_missing_component_is_omitted_not_zeroed():
    partial = json.dumps({"business_health": {"score": 60, "notes": "ok"}})
    out = _parse_scores(partial, ticker="NVDA")
    assert set(out) == {"Business Health"}
    assert "Insider Alignment" not in out  # omitted → caller carries forward


def test_parse_malformed_score_is_omitted():
    bad = json.dumps(
        {
            "business_health": {"score": "high", "notes": "not numeric"},
            "thesis_integrity": {"score": 70, "notes": "fine"},
        }
    )
    out = _parse_scores(bad, ticker="NVDA")
    assert "Business Health" not in out
    assert out["Thesis Integrity"].score == 70


def test_parse_clamps_out_of_range_scores():
    wild = json.dumps(
        {
            "business_health": {"score": 150, "notes": "over"},
            "insider_alignment": {"score": -5, "notes": "under"},
            "thesis_integrity": {"score": 70.6, "notes": "float"},
        }
    )
    out = _parse_scores(wild, ticker="NVDA")
    assert out["Business Health"].score == 100
    assert out["Insider Alignment"].score == 0
    assert out["Thesis Integrity"].score == 70


# ---- failure semantics -----------------------------------------------------


def test_no_token_returns_empty(capsys):
    # conftest strips ZO_CLIENT_IDENTITY_TOKEN for every test.
    assert _score() == {}
    assert "carrying forward" in capsys.readouterr().err


def test_call_failure_returns_empty_after_retries(monkeypatch, capsys):
    monkeypatch.setenv("ZO_CLIENT_IDENTITY_TOKEN", "fake-token")
    calls = {"n": 0}

    def boom(prompt, *, token):
        calls["n"] += 1
        raise OSError("network down")

    monkeypatch.setattr(llm_scores, "_call_zo_ask", boom)
    monkeypatch.setattr(llm_scores.time, "sleep", lambda s: None)

    assert _score() == {}
    assert calls["n"] == 1 + llm_scores._MAX_RETRIES
    err = capsys.readouterr().err
    assert "network down" in err
    assert "carrying forward" in err


def test_successful_call_returns_components(monkeypatch):
    monkeypatch.setenv("ZO_CLIENT_IDENTITY_TOKEN", "fake-token")
    monkeypatch.setattr(llm_scores, "_call_zo_ask", lambda prompt, *, token: GOOD_RESPONSE)
    out = _score()
    assert len(out) == 3
    assert out["Business Health"].score == 82


def test_model_env_omitted_by_default(monkeypatch):
    """Without CLARION_LLM_SCORES_MODEL, the payload has no model_name."""
    monkeypatch.setenv("ZO_CLIENT_IDENTITY_TOKEN", "fake-token")
    monkeypatch.delenv("CLARION_LLM_SCORES_MODEL", raising=False)
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"output": GOOD_RESPONSE}).encode()

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        captured["auth"] = req.headers.get("Authorization")
        return FakeResp()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = _score()
    assert len(out) == 3
    assert "model_name" not in captured["body"]
    assert captured["auth"] == "fake-token"

    monkeypatch.setenv("CLARION_LLM_SCORES_MODEL", "zo:openai/gpt-5.4-mini")
    _score()
    assert captured["body"]["model_name"] == "zo:openai/gpt-5.4-mini"


# ---- prompt construction ---------------------------------------------------


def test_prompt_includes_thesis_and_prices():
    p = llm_scores._build_prompt(
        ticker="NVDA",
        thesis_markdown="UNIQUE-THESIS-BODY",
        current_price=101.5,
        base_case_fair_value=120.0,
    )
    assert "UNIQUE-THESIS-BODY" in p
    assert "$101.50" in p
    assert "$120.00" in p
    assert "business_health" in p


def test_prompt_handles_missing_prices():
    p = llm_scores._build_prompt(
        ticker="NVDA",
        thesis_markdown="body",
        current_price=None,
        base_case_fair_value=None,
    )
    assert "unknown" in p
