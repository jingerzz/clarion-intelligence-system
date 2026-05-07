"""Preset JSON schemas + Repair specs for common /zo/ask tasks.

When adding a new schema:
- Use 'number' for integer-valued fields. The Zo API rejects 'integer'.
  Call as_int() on read.
- Declare a Repair spec for any non-strict model that may rename keys
  (zo:minimax/* tend to return 'summary' instead of 'one_sentence_summary'
  and similar near-miss aliases).
- Keep the schema flat where possible — top-level shape_check is light.
"""

from __future__ import annotations

from ai_buffett_zo.llm.zo_client import Repair

# --- 10-K / 10-Q section summary --------------------------------------------
# Used by sec-indexer when summarizing filing sections. Validated against
# zo:openai/gpt-5.4-mini (strict), zo:minimax/minimax-m2.5 (strict-with-repair),
# zo:minimax/minimax-m2.7 (best-effort).

SECTION_SUMMARY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "one_sentence_summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "themes": {"type": "array", "items": {"type": "string"}},
        "severity": {"type": "number"},  # 1 (benign) - 5 (existential); use as_int
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

SECTION_SUMMARY_REPAIR = Repair(
    aliases={
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
    },
    defaults={
        "one_sentence_summary": "",
        "key_points": [],
        "themes": [],
        "severity": 0,
        "tickers_or_entities": [],
    },
)
