#!/usr/bin/env python3
"""
zo_ask_prototype.py — minimal /zo/ask client for sec-indexer summarization.

Validates the swap-point for pageindex llm.py before doing the real refactor.

Usage:
    python zo_ask_prototype.py [--model MODEL_NAME] [--text "..."]
    python zo_ask_prototype.py --list-models

Auth:
    Reads ZO_API_KEY from env. Falls back to ZO_CLIENT_IDENTITY_TOKEN
    (auto-injected when run inside an active Zo agent turn).

Findings worth knowing before you hard-wire this in:
- Endpoint: https://api.zo.computer/zo/ask  (POST, JSON)
- output_format scalars: type must be 'string' | 'number' | 'boolean'.
  No 'integer'. Use 'number' and cast to int yourself if needed.
- Schema strictness varies by model. As of 2026-05:
    * zo:openai/gpt-5.4-mini    -> strict, returns exact key set.
    * zo:minimax/minimax-m2.7   -> best-effort, may rename keys / drop fields.
  -> always validate + repair before trusting the response.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.zo.computer/zo/ask"
MODELS_URL = "https://api.zo.computer/models/available"

# --- Schema for a 10-K section summary ----------------------------------------
SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "one_sentence_summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "themes": {"type": "array", "items": {"type": "string"}},
        "severity": {"type": "number"},  # 1-5; integer not allowed by API
        "tickers_or_entities": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "one_sentence_summary",
        "key_points",
        "themes",
        "severity",
        "tickers_or_entities",
    ],
}


def _auth_token() -> str:
    tok = os.environ.get("ZO_API_KEY") or os.environ.get("ZO_CLIENT_IDENTITY_TOKEN")
    if not tok:
        sys.exit(
            "error: set ZO_API_KEY (Settings > Advanced > Secrets) "
            "or run inside a Zo agent turn (ZO_CLIENT_IDENTITY_TOKEN)."
        )
    return tok


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_auth_token()}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {_auth_token()}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_models() -> list[dict]:
    return _get_json(MODELS_URL).get("models", [])


# --- Validation / repair ------------------------------------------------------
def validate_section_summary(out: dict) -> tuple[bool, list[str]]:
    """Return (ok, missing_or_wrong_keys)."""
    if not isinstance(out, dict):
        return False, ["not an object"]
    problems: list[str] = []
    for key in SECTION_SCHEMA["required"]:
        if key not in out:
            problems.append(f"missing:{key}")
            continue
        spec = SECTION_SCHEMA["properties"][key]
        v = out[key]
        if spec["type"] == "string" and not isinstance(v, str):
            problems.append(f"wrongtype:{key}")
        elif spec["type"] == "number" and not isinstance(v, (int, float)):
            problems.append(f"wrongtype:{key}")
        elif spec["type"] == "array" and not isinstance(v, list):
            problems.append(f"wrongtype:{key}")
    return (not problems), problems


def repair_section_summary(raw: dict) -> dict:
    """Best-effort key normalization for non-strict models like MiniMax."""
    if not isinstance(raw, dict):
        return {}
    aliases = {
        "summary": "one_sentence_summary",
        "one_line_summary": "one_sentence_summary",
        "headline": "one_sentence_summary",
        "bullets": "key_points",
        "points": "key_points",
        "topics": "themes",
        "tags": "themes",
        "risk_level": "severity",
        "score": "severity",
        "entities": "tickers_or_entities",
        "tickers": "tickers_or_entities",
    }
    out = {aliases.get(k, k): v for k, v in raw.items()}
    out.setdefault("key_points", [])
    out.setdefault("themes", [])
    out.setdefault("tickers_or_entities", [])
    out.setdefault("severity", 0)
    out.setdefault("one_sentence_summary", "")
    return out


# --- Core call ----------------------------------------------------------------
def summarize_section(
    text: str,
    model_name: str = "zo:openai/gpt-5.4-mini",
    section_label: str = "Risk Factors",
    max_retries: int = 1,
) -> dict:
    prompt = (
        f"You are summarizing a 10-K {section_label} section for a quant research database. "
        f"Be precise, neutral, and factual. Do not speculate.\n\n"
        f"Return JSON matching the provided schema exactly. "
        f"`severity` is 1 (benign) to 5 (existential). "
        f"`tickers_or_entities` are tickers, company names, or specific named entities mentioned.\n\n"
        f"--- TEXT ---\n{text}\n--- END ---"
    )
    payload = {
        "input": prompt,
        "model_name": model_name,
        "output_format": SECTION_SCHEMA,
    }
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            t0 = time.time()
            resp = _post_json(API_URL, payload)
            elapsed = time.time() - t0
            raw = resp.get("output", {})
            repaired = repair_section_summary(raw if isinstance(raw, dict) else {})
            ok, problems = validate_section_summary(repaired)
            return {
                "ok": ok,
                "model": model_name,
                "elapsed_s": round(elapsed, 2),
                "problems": problems,
                "raw_output": raw,
                "summary": repaired,
                "conversation_id": resp.get("conversation_id"),
            }
        except urllib.error.HTTPError as e:
            last_err = e
            err_body = e.read().decode("utf-8", "ignore")
            if attempt < max_retries:
                time.sleep(1 + attempt)
                continue
            return {"ok": False, "model": model_name, "error": str(e), "body": err_body}
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries:
                time.sleep(1 + attempt)
                continue
            return {"ok": False, "model": model_name, "error": str(e)}
    return {"ok": False, "model": model_name, "error": str(last_err)}


# --- CLI ----------------------------------------------------------------------
SAMPLE = (
    "Our business depends on the continued availability of advanced AI accelerators "
    "from a small number of suppliers. Supply constraints, export controls, or "
    "geopolitical disruptions could materially impact our ability to deliver products "
    "on time and at expected gross margins. In addition, intensifying competition "
    "from open-source model providers may erode pricing power in the inference market."
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="zo:openai/gpt-5.4-mini")
    ap.add_argument("--text", default=SAMPLE)
    ap.add_argument("--section", default="Risk Factors")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    if args.list_models:
        for m in list_models():
            print(f"  {m['model_name']:<40s}  ctx={m['context_window']:>8d}  "
                  f"{m['type']:<11s}  {m['vendor']}")
        return

    result = summarize_section(args.text, model_name=args.model, section_label=args.section)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
