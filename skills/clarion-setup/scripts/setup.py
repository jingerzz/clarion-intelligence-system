#!/usr/bin/env python3
"""Clarion Intelligence System setup script.

Run from the cloned repo root (or any cwd — paths are resolved from this
script's location). Idempotent.

Steps:
1. Validate uv is on PATH.
2. uv pip install -e {repo}/lib  (with --system if no venv is active)
3. mkdir -p ~/clarion/{data/equities,sec,queue,theses,watchlists,letters}
4. Write ~/clarion/config.json if missing
5. Verify `sec-indexer` console script resolves
6. Print service registration envelope for the SKILL.md to consume
7. Print SETUP_RESULT: ok | error: <reason>

The SKILL.md parses stdout; structured output goes between
`--- BEGIN SERVICE_REGISTRATION ---` and `--- END SERVICE_REGISTRATION ---`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]   # skills/clarion-setup/scripts/setup.py → repo
LIB_DIR = REPO_ROOT / "lib"
WORKSPACE = Path.home() / "clarion"
DATA_SUBDIRS = (
    "data/equities",
    "sec",
    "queue",
    "theses",
    "watchlists",
    "letters",
)

DEFAULT_CONFIG: dict = {
    "indexing_model": "zo:openai/gpt-5.4-mini",
    "indexing_fallback_model": "zo:minimax/minimax-m2.5",
    "reasoning_model": "zo:anthropic/claude-opus-4-7",
    "sec_user_agent": "Clarion Intelligence System (clarion@example.com)",
    "data_root": str(WORKSPACE),
}

SERVICE_REGISTRATION_PARAMS: dict = {
    "label": "sec-indexer",
    "mode": "process",
    "entrypoint": "sec-indexer",
    "workdir": "/home/workspace",
    "env_vars": {"ZO_API_KEY": "$ZO_API_KEY"},
    "description": "Clarion sec-indexer — background SEC EDGAR filing indexer",
}


# Verbatim user-facing message for the only manual step in setup. The chat
# agent that invokes setup.py is expected to paste this between the BEGIN/END
# sentinels into the user's chat unchanged — no summarization, no rewording.
# The detail level here is deliberate: a non-technical user needs the exact
# menu paths, the exact secret name, and the numbered sequence.
USER_ACTION_MESSAGE = """\
**Action required (1 of 1 manual step)** — Create your `ZO_API_KEY` secret

Clarion's `sec-indexer` background service needs a Zo access token to call \
models on your behalf. This token is **Zo-issued** (no OpenAI / Anthropic / \
external keys involved) and bills against your Zo monthly credit pool — the \
same pool as your chat usage.

This is the **only** manual step in the entire setup. Total time: ~2 minutes.

---

**Step 1 — Create an access token**

1. Open Zo Settings (top-right menu icon → **Settings**, or however your Zo client surfaces settings).
2. Go to **Advanced → Access Tokens**.
3. Click **Create token** (or the equivalent "+ New token" button).
4. Name the token anything you like — `clarion-sec-indexer` is a good default.
5. **Copy the token value.** It starts with `zo_sk_`. You'll paste it in Step 2.

**Step 2 — Save it as a secret**

1. In the same Settings area, go to **Advanced → Secrets**.
2. Click **Create secret** (or "+ New secret").
3. **Name:** type exactly `ZO_API_KEY` — uppercase, with the underscore. The indexer service looks for a secret with this exact name; any other spelling (lowercase, hyphens, etc.) will not be found.
4. **Value:** paste the token you copied in Step 1.
5. Save.

**Step 3 — Confirm**

Reply with **`done`** in this chat. I'll automatically register the indexer service for you and finish setup.

---

*If you can't find the menu items above, your Zo client UI may use slightly different labels — search for "Access Tokens" and "Secrets" in your settings. If you get stuck, tell me what you see and I'll help.*\
"""


def fail(msg: str) -> None:
    """Emit the error sentinel and exit non-zero."""
    print(f"\nSETUP_RESULT: error: {msg}", flush=True)
    sys.exit(1)


def ok() -> None:
    print("\nSETUP_RESULT: ok", flush=True)


# ---- pure helpers (testable) -----------------------------------------------


def make_data_tree(workspace: Path) -> list[Path]:
    """Create the per-user data tree under workspace. Idempotent."""
    out: list[Path] = []
    for sub in DATA_SUBDIRS:
        d = workspace / sub
        d.mkdir(parents=True, exist_ok=True)
        out.append(d)
    return out


def write_default_config(workspace: Path, *, force: bool = False) -> Path:
    """Write workspace/config.json with defaults. Preserved if exists unless force=True."""
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "config.json"
    if path.exists() and not force:
        return path
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
    return path


def install_library(lib_dir: Path) -> tuple[int, str, str]:
    """uv pip install -e {lib_dir}. Adds --system if no venv is active.

    Returns (returncode, stdout, stderr). Caller decides what to do.
    """
    in_venv = bool(os.environ.get("VIRTUAL_ENV"))
    cmd = ["uv", "pip", "install", "--quiet", "-e", str(lib_dir)]
    if not in_venv:
        cmd.insert(3, "--system")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def verify_console_script() -> tuple[int, str]:
    """Confirm `sec-indexer --help` works. Returns (returncode, captured_output)."""
    result = subprocess.run(
        ["sec-indexer", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


# ---- main orchestration ----------------------------------------------------


def main() -> None:
    print("Clarion Intelligence System — setup\n")

    # Step 1 — uv on PATH
    if shutil.which("uv") is None:
        fail("uv not found on PATH. Install uv: https://docs.astral.sh/uv/")

    # Step 2 — install library
    if not LIB_DIR.is_dir():
        fail(f"library directory missing: {LIB_DIR} (is the repo cloned?)")

    print(f"[1/5] Installing ai_buffett_zo from {LIB_DIR} ...")
    rc, _, stderr = install_library(LIB_DIR)
    if rc != 0:
        fail(f"uv pip install failed (rc={rc}): {stderr.strip()[:300]}")
    print("       installed.")

    # Step 3 — data tree
    print(f"[2/5] Creating data tree under {WORKSPACE} ...")
    created = make_data_tree(WORKSPACE)
    for d in created:
        print(f"       {d}")

    # Step 4 — config
    print("[3/5] Writing default config ...")
    config_path = write_default_config(WORKSPACE)
    if config_path.read_text().strip() == json.dumps(DEFAULT_CONFIG, indent=2).strip():
        print(f"       wrote {config_path}")
    else:
        print(f"       preserved existing {config_path}")

    # Step 5 — entrypoint check
    print("[4/5] Verifying sec-indexer entry point ...")
    rc, output = verify_console_script()
    if rc != 0:
        fail(
            "sec-indexer entry point not on PATH after install. "
            "uv may have installed to a directory not in PATH. "
            f"Output:\n{output[:300]}"
        )
    print("       OK")

    # Step 6 — registration envelope
    print("[5/5] Service registration parameters:")
    print("--- BEGIN SERVICE_REGISTRATION ---")
    print(json.dumps(SERVICE_REGISTRATION_PARAMS, indent=2))
    print("--- END SERVICE_REGISTRATION ---")

    # User-facing message for the only manual step. The agent invoking this
    # script must paste the block between BEGIN/END sentinels into chat
    # verbatim — see SKILL.md Step 3.
    print()
    print("--- BEGIN USER_ACTION_REQUIRED ---")
    print(USER_ACTION_MESSAGE)
    print("--- END USER_ACTION_REQUIRED ---")

    # If sec-indexer is already running from a previous setup, an editable
    # install does NOT reload it — the running process keeps the modules it
    # imported at startup. The skill caller must restart the service after a
    # re-run, otherwise upstream bug fixes won't take effect.
    print(
        "\nNOTE: if `sec-indexer` is already registered as a running service "
        "(re-run scenario), the user does NOT need to redo the secret step. "
        "Skip the USER_ACTION_REQUIRED block above and restart the service "
        "via `update_user_service` with action=restart so any updated source "
        "code is loaded into the running process."
    )

    ok()


if __name__ == "__main__":
    main()
