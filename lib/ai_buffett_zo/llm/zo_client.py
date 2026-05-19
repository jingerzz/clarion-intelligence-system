"""Generic client for Zo Computer's /zo/ask endpoint.

The endpoint is the agent layer — `model_name` selects the model, `output_format`
declares a JSON Schema for typed output. Returned through `ZoClient.ask()` which
applies an optional `Repair` pass and shape-checks the result.

Auth: bearer token from $ZO_API_KEY (recommended for long-running services) or
$ZO_CLIENT_IDENTITY_TOKEN (auto-injected only during agent turns).

Schema constraint: scalar `type` must be `string` | `number` | `boolean`.
The API rejects `integer`. Use `number` and call `as_int()` on read.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API_URL = "https://api.zo.computer/zo/ask"
MODELS_URL = "https://api.zo.computer/models/available"

# Hardcoded last-resort fallbacks. These are the values used if
# ~/clarion/config.json doesn't exist, can't be parsed, or doesn't contain
# the relevant key. Set by ARCHITECTURE.md — override per-call as needed,
# or globally by editing the user's ~/clarion/config.json.
_FALLBACK_MODEL_INDEX = "zo:openai/gpt-5.4-mini"          # cheap, strict, free tier
_FALLBACK_MODEL_INDEX_FALLBACK = "zo:minimax/minimax-m2.5"  # free, fast, repair pass needed
_FALLBACK_MODEL_REASONING = "zo:anthropic/claude-opus-4-7"  # subscriber tier; for synthesis


def _load_config_models() -> dict[str, str]:
    """Resolve model defaults from ~/clarion/config.json with hardcoded fallback.

    Read once at module-import time. The indexer (long-running service) and
    every caller importing ``DEFAULT_MODEL_INDEX`` / ``DEFAULT_MODEL_INDEX_FALLBACK``
    / ``DEFAULT_MODEL_REASONING`` see whichever value was current when their
    process started. To pick up edits to ``config.json``, restart the process —
    same contract as editable ``uv pip install -e`` (in-memory modules don't
    auto-reload).

    Resolution order, per key:
      1. ``config.json``'s value for the key, if the file exists, parses, and
         the key is present and non-empty.
      2. The hardcoded ``_FALLBACK_*`` value.

    Empty strings, missing keys, and malformed files all fall through to (2)
    — never silently use an empty model name.
    """
    # Lazy-imported to avoid any chance of a circular import at module load
    # via the llm/__init__.py re-export path.
    from ai_buffett_zo._paths import clarion_home

    defaults = {
        "indexing_model": _FALLBACK_MODEL_INDEX,
        "indexing_fallback_model": _FALLBACK_MODEL_INDEX_FALLBACK,
        "reasoning_model": _FALLBACK_MODEL_REASONING,
    }

    config_path = clarion_home() / "config.json"
    if not config_path.exists():
        return defaults

    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(config, dict):
        return defaults

    return {
        key: (config.get(key) or fallback)
        for key, fallback in defaults.items()
    }


_models = _load_config_models()
DEFAULT_MODEL_INDEX = _models["indexing_model"]
DEFAULT_MODEL_INDEX_FALLBACK = _models["indexing_fallback_model"]
DEFAULT_MODEL_REASONING = _models["reasoning_model"]


class ZoLLMError(Exception):
    """Base error for Zo LLM calls."""


class ZoAuthError(ZoLLMError):
    """Missing or invalid Zo bearer token."""


class ZoSchemaError(ZoLLMError):
    """An output_format schema violates Zo API constraints (e.g. uses 'integer')."""


@dataclass
class Repair:
    """Declarative repair spec for non-strict model outputs.

    aliases: map of {wrong_key: canonical_key} — applied first, before defaults.
    defaults: required keys with default values when missing.

    Models like zo:minimax/* may rename keys (e.g. 'summary' instead of
    'one_sentence_summary'). The repair pass runs after the API call so
    downstream code never sees a malformed object.
    """

    aliases: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)

    def apply(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            return dict(self.defaults)
        out = {self.aliases.get(k, k): v for k, v in raw.items()}
        for key, default in self.defaults.items():
            out.setdefault(key, default)
        return out


@dataclass
class AskResult:
    """Outcome of a /zo/ask call.

    ok: True iff (no transport error) AND (if schema'd, no shape problems remain).
    data: parsed payload — dict if output_format was supplied, str otherwise.
    raw: untouched API output, for debugging or escape hatches.
    problems: list of shape-check issues (only relevant for schema'd calls).
    """

    ok: bool
    data: Any
    raw: Any
    elapsed_s: float
    model: str
    problems: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    error: str | None = None


def as_int(value: Any) -> int:
    """Cast a Zo-returned 'number' field to int.

    Use on severity/score/count fields where the schema declares 'number'
    (because the API rejects 'integer') but the domain is integer-valued.
    """
    if value is None or value == "":
        return 0
    return int(round(float(value)))


def _validate_schema(schema: dict) -> None:
    """Walk a JSON Schema dict and raise if it uses 'integer' (rejected by Zo API).

    Catches the constraint at compose-time instead of at call-time.
    """

    def walk(node: Any, path: str = "$") -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "integer":
            raise ZoSchemaError(
                f"Zo /zo/ask rejects scalar type 'integer' at {path}. "
                f"Use 'number' and as_int() on read."
            )
        for key in ("properties", "patternProperties"):
            sub = node.get(key)
            if isinstance(sub, dict):
                for k, v in sub.items():
                    walk(v, f"{path}.{k}")
        for key in ("items", "additionalProperties"):
            if key in node:
                walk(node[key], f"{path}.{key}")
        for key in ("anyOf", "oneOf", "allOf"):
            branches = node.get(key)
            if isinstance(branches, list):
                for i, branch in enumerate(branches):
                    walk(branch, f"{path}[{key}:{i}]")

    walk(schema)


def _shape_check(data: Any, schema: dict) -> list[str]:
    """Light shape validation against a JSON Schema. Reports problems, doesn't raise.

    Only validates the top level of an object schema — enough to catch the
    common failure modes (missing required keys, wrong scalar type) without
    becoming a full schema validator.
    """
    problems: list[str] = []
    if schema.get("type") != "object":
        return problems
    if not isinstance(data, dict):
        return ["not an object"]
    props = schema.get("properties", {})
    required = schema.get("required", list(props.keys()))
    for key in required:
        if key not in data:
            problems.append(f"missing:{key}")
            continue
        spec = props.get(key, {})
        v = data[key]
        t = spec.get("type")
        if t == "string" and not isinstance(v, str):
            problems.append(f"wrongtype:{key} (want string)")
        elif t == "number" and not isinstance(v, int | float):
            problems.append(f"wrongtype:{key} (want number)")
        elif t == "boolean" and not isinstance(v, bool):
            problems.append(f"wrongtype:{key} (want boolean)")
        elif t == "array" and not isinstance(v, list):
            problems.append(f"wrongtype:{key} (want array)")
        elif t == "object" and not isinstance(v, dict):
            problems.append(f"wrongtype:{key} (want object)")
    return problems


class ZoClient:
    """Client for Zo Computer's /zo/ask endpoint.

    Reads bearer token from $ZO_API_KEY (recommended for services) or
    $ZO_CLIENT_IDENTITY_TOKEN (auto-injected during agent turns).

    Use ask() for one-shot calls. Pass output_format + repair for typed JSON output.
    Use list_models() to enumerate available models.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        default_model: str = DEFAULT_MODEL_INDEX,
        api_url: str = API_URL,
        timeout: int = 120,
        max_retries: int = 1,
    ) -> None:
        self._explicit_token = token
        self.default_model = default_model
        self.api_url = api_url
        self.timeout = timeout
        self.max_retries = max_retries

    def _token(self) -> str:
        tok = (
            self._explicit_token
            or os.environ.get("ZO_API_KEY")
            or os.environ.get("ZO_CLIENT_IDENTITY_TOKEN")
        )
        if not tok:
            raise ZoAuthError(
                "no Zo bearer token. Set ZO_API_KEY (Settings > Advanced > Secrets) "
                "or run inside a Zo agent turn (ZO_CLIENT_IDENTITY_TOKEN auto-injected)."
            )
        return tok

    def ask(
        self,
        input: str,
        *,
        model: str | None = None,
        output_format: dict | None = None,
        repair: Repair | None = None,
    ) -> AskResult:
        """One-shot /zo/ask call.

        If `output_format` is supplied, the schema is validated for the 'integer'
        constraint at compose time, then `repair` (if given) is applied to the
        response, and the result is shape-checked. `data` will be a dict.

        If `output_format` is None, the call is free-form and `data` is a string.

        On transport error, returns AskResult with `ok=False` and `error` populated;
        does not raise (matches the global rule for tool-style returns).
        """
        if output_format is not None:
            _validate_schema(output_format)
        model_name = model or self.default_model

        payload: dict = {"input": input, "model_name": model_name}
        if output_format is not None:
            payload["output_format"] = output_format

        last_err: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.time()
                resp = self._post_json(self.api_url, payload)
                elapsed = time.time() - t0
                raw_output = resp.get("output")
                conv_id = resp.get("conversation_id")

                if output_format is not None:
                    data = (
                        repair.apply(raw_output)
                        if repair is not None
                        else (raw_output if isinstance(raw_output, dict) else {})
                    )
                    problems = _shape_check(data, output_format)
                    return AskResult(
                        ok=not problems,
                        data=data,
                        raw=raw_output,
                        elapsed_s=round(elapsed, 2),
                        model=model_name,
                        problems=problems,
                        conversation_id=conv_id,
                    )

                text = raw_output if isinstance(raw_output, str) else json.dumps(raw_output)
                return AskResult(
                    ok=True,
                    data=text,
                    raw=raw_output,
                    elapsed_s=round(elapsed, 2),
                    model=model_name,
                    conversation_id=conv_id,
                )

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")
                last_err = f"HTTP {e.code}: {body[:500]}"
            except (urllib.error.URLError, json.JSONDecodeError, OSError, TimeoutError) as e:
                last_err = f"{type(e).__name__}: {e}"

            if attempt < self.max_retries:
                time.sleep(1 + attempt)

        return AskResult(
            ok=False,
            data=None,
            raw=None,
            elapsed_s=0.0,
            model=model_name,
            error=last_err or "unknown error",
        )

    def list_models(self) -> list[dict]:
        """Enumerate models available to the authenticated Zo account.

        Returns the raw list from GET /models/available. Each entry has at
        minimum `model_name`, `vendor`, `context_window`, `type` (free vs
        subscribers), and routing hints.
        """
        req = urllib.request.Request(
            MODELS_URL,
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("models", [])

    def _post_json(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
