"""LLM-driven health component scoring via /zo/ask.

Three components can't be scored algorithmically from a few numbers — they
need to read the thesis prose and reason over it:

    Business Health   — revenue growth, margin trends, competitive position, balance sheet
    Insider Alignment — insider transactions, compensation structure, share count trends
    Thesis Integrity  — whether the core claims still hold, evidence remains valid,
                         logic intact, kill conditions are still appropriate

This module sends the full thesis markdown to a child Zo invocation via
the /zo/ask API and extracts structured scores + notes from the response.

Why /zo/ask instead of an LLM library call:
    - Same model as the parent — no dependency drift.
    - Inherits the workspace, file access, and persona rules.
    - We want the agent's judgment, not raw model output — the agent
      can cross-reference SEC filings, check yfinance, and spot
      inconsistencies that raw text scoring would miss.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ai_buffett_zo.theses.types import HealthComponent

_API = "https://api.zo.computer/zo/ask"

# Model for the scoring call. Unset (default) omits model_name so the
# child invocation uses the Zo account's default model. Override with
# e.g. CLARION_LLM_SCORES_MODEL="zo:openai/gpt-5.4-mini" to pin a cheap
# model for this high-frequency, low-difficulty scoring task.
_MODEL_ENV = "CLARION_LLM_SCORES_MODEL"

# Timeout for each /zo/ask invocation (seconds). 3 components in one call,
# but the model needs to read a full thesis — generous timeout.
_REQUEST_TIMEOUT = 120

# Retries for transient failures.
_MAX_RETRIES = 2
_RETRY_DELAY_S = 5


def score_thesis_with_llm(
    *,
    ticker: str,
    thesis_markdown: str,
    current_price: float | None,
    base_case_fair_value: float | None,
) -> dict[str, HealthComponent]:
    """Score Business Health, Insider Alignment, and Thesis Integrity.

    Returns a dict of successfully-scored HealthComponents, keyed by
    display name. On failure (no token, network error, timeout, unparseable
    response) the failed components are OMITTED — never zero-filled — so
    the caller carries forward previous scores instead of cratering the
    Overall score with fabricated zeros.

    The prompt includes the full thesis markdown so the agent can reason
    over claims, evidence citations, financial data, and kill conditions.
    """
    import sys

    token = os.environ.get("ZO_CLIENT_IDENTITY_TOKEN")
    if not token:
        print(
            "llm_scores: ZO_CLIENT_IDENTITY_TOKEN not set — carrying forward "
            "previous LLM component scores",
            file=sys.stderr,
        )
        return {}

    prompt = _build_prompt(
        ticker=ticker,
        thesis_markdown=thesis_markdown,
        current_price=current_price,
        base_case_fair_value=base_case_fair_value,
    )

    for attempt in range(1 + _MAX_RETRIES):
        try:
            result = _call_zo_ask(prompt, token=token)
            return _parse_scores(result, ticker=ticker)
        except Exception as e:
            print(
                f"llm_scores: {ticker} attempt {attempt + 1}/{1 + _MAX_RETRIES} "
                f"failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_S)
            continue

    print(
        f"llm_scores: {ticker} scoring failed after {1 + _MAX_RETRIES} attempts — "
        "carrying forward previous LLM component scores",
        file=sys.stderr,
    )
    return {}


def _build_prompt(
    *,
    ticker: str,
    thesis_markdown: str,
    current_price: float | None,
    base_case_fair_value: float | None,
) -> str:
    price_str = f"${current_price:.2f}" if current_price is not None else "unknown"
    fv_str = f"${base_case_fair_value:.2f}" if base_case_fair_value is not None else "unknown"

    return f"""You are scoring an investment thesis for {ticker}. Current price: {price_str}. Base case fair value: {fv_str}.

Read the full thesis below and score THREE dimensions. Return ONLY valid JSON — no markdown, no commentary before or after.

Scoring rubric for each dimension (0-100):

**Business Health** (weight 20%): Assess revenue growth trajectory, margin trends (gross and operating), competitive position durability, balance sheet strength. A healthy business grows revenue, maintains or expands margins, and has a manageable debt load.
- 90-100: Accelerating revenue, expanding margins, fortress balance sheet
- 70-89: Steady growth, stable margins, conservative leverage
- 50-69: Decelerating growth, margin pressure, above-average leverage
- 30-49: Stalling revenue, declining margins, concerning leverage
- 0-29: Revenue shrinking, margin collapse, distressed balance sheet

**Insider Alignment** (weight 10%): Assess insider buying/selling patterns (if mentioned), compensation structure alignment with shareholders, share count changes over time (buybacks or dilution). Insider buying is bullish; heavy selling without stated reason is bearish; aggressive buybacks that reduce share count are a positive signal.
- 90-100: Heavy insider buying, rational compensation, aggressive buybacks reducing share count
- 70-89: Moderate insider buying or strong buybacks, compensation aligned
- 50-69: Neutral — no concerning signals but nothing notably positive
- 30-49: Insider selling (non-diversification), dilutive comp, share count growing
- 0-29: Heavy insider selling, egregious comp, massive dilution

**Thesis Integrity** (weight 25%): Assess whether the core claims in "What I Believe" still hold, whether the evidence cited remains valid, whether the valuation assumptions are reasonable at the current price, and whether the kill conditions are specific, measurable, and appropriate. A strong thesis has falsifiable claims, current evidence, and kill conditions that are binary triggers.
- 90-100: Core claims intact and strengthened, evidence current, kill conditions sharp and binary
- 70-89: Core claims mostly hold, evidence reasonable, kill conditions adequate
- 50-69: Some claims weakening or evidence going stale, kill conditions could be tighter
- 30-49: Core thesis showing cracks, evidence outdated, kill conditions vague
- 0-29: Thesis broken — claims contradicted by recent data, evidence invalidated

For each dimension, include:
- "score": integer 0-100
- "notes": 1-2 sentence explanation with specific observations from the thesis text

Return this exact JSON structure:
{{
  "business_health": {{ "score": 0, "notes": "..." }},
  "insider_alignment": {{ "score": 0, "notes": "..." }},
  "thesis_integrity": {{ "score": 0, "notes": "..." }}
}}

THESIS TO EVALUATE:
---
{thesis_markdown}
---
"""


def _call_zo_ask(prompt: str, *, token: str) -> str:
    """Post to /zo/ask and return the raw text output.

    The child Zo returns its response as text in the "output" field.
    The caller strips any markdown fences and parses JSON from it.
    """
    import urllib.request

    payload: dict[str, Any] = {"input": prompt}
    model = os.environ.get(_MODEL_ENV, "").strip()
    if model:
        payload["model_name"] = model
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        _API,
        data=body,
        headers={
            "authorization": token,
            "content-type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    output = data.get("output", "")
    if not isinstance(output, str):
        raise ValueError(f"Unexpected /zo/ask output type: {type(output)}")

    return output


def _parse_scores(
    raw: str,
    *,
    ticker: str,
) -> dict[str, HealthComponent]:
    """Extract the three component scores from the LLM response.

    Handles responses wrapped in ```json fences, bare JSON, or markdown
    that contains an embedded JSON object. Components that are missing
    or malformed are omitted from the result (carried forward by the
    caller) — never zero-filled.
    """
    json_str = raw.strip()

    # Strip ```json / ``` fences if present.
    if json_str.startswith("```"):
        json_str = json_str.split("\n", 1)[-1] if "\n" in json_str else ""
        if json_str.endswith("```"):
            json_str = json_str[:-3].strip()

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        # Try to find a JSON object in the response.
        import re
        match = re.search(r'\{.*"business_health".*\}', raw, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    if not isinstance(parsed, dict):
        return {}

    out: dict[str, HealthComponent] = {}
    for json_key, display_name in (
        ("business_health", "Business Health"),
        ("insider_alignment", "Insider Alignment"),
        ("thesis_integrity", "Thesis Integrity"),
    ):
        hc = _extract_component(parsed, json_key, display_name, ticker)
        if hc is not None:
            out[display_name] = hc
    return out


def _extract_component(
    data: dict,
    json_key: str,
    display_name: str,
    ticker: str,
) -> HealthComponent | None:
    inner = data.get(json_key)
    if not isinstance(inner, dict) or not isinstance(inner.get("score"), (int, float)):
        return None

    score = _clamp_score(inner.get("score"))
    notes = str(inner.get("notes", "")).strip()
    if not notes:
        notes = f"{display_name} scored {score}/100 by LLM for {ticker}"

    return HealthComponent(
        name=display_name,
        weight=_DEFAULT_WEIGHTS.get(display_name, 0),
        score=score,
        notes=notes,
    )


_DEFAULT_WEIGHTS = {
    "Business Health": 20,
    "Insider Alignment": 10,
    "Thesis Integrity": 25,
}


def _clamp_score(value: object) -> int:
    if isinstance(value, (int, float)):
        return max(0, min(100, int(value)))
    return 0
