"""Tests for skills/clarion-setup/scripts/setup.py.

The script is loaded as a module via importlib so we can exercise its
helpers directly without invoking subprocess. The subprocess paths
(install_library, verify_console_script) are exercised by Phase A's
end-to-end test on Zo, not here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_PATH = REPO_ROOT / "skills" / "clarion-setup" / "scripts" / "setup.py"


@pytest.fixture(scope="module")
def setup_mod():
    """Load setup.py as a module. Fixture scope=module to load only once."""
    spec = importlib.util.spec_from_file_location("clarion_setup", SETUP_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_setup"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_make_data_tree_creates_all_subdirs(setup_mod, tmp_path: Path) -> None:
    workspace = tmp_path / "clarion"
    paths = setup_mod.make_data_tree(workspace)
    assert {p.relative_to(workspace).as_posix() for p in paths} == set(setup_mod.DATA_SUBDIRS)
    for p in paths:
        assert p.is_dir()


def test_make_data_tree_idempotent(setup_mod, tmp_path: Path) -> None:
    workspace = tmp_path / "clarion"
    setup_mod.make_data_tree(workspace)
    setup_mod.make_data_tree(workspace)  # second call must not raise
    assert (workspace / "sec").is_dir()


def test_write_default_config_creates_when_missing(setup_mod, tmp_path: Path) -> None:
    path = setup_mod.write_default_config(tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["indexing_model"] == "zo:openai/gpt-5.4-mini"
    assert data["data_root"]


def test_write_default_config_preserves_existing(setup_mod, tmp_path: Path) -> None:
    custom = {"indexing_model": "custom-model", "user_pref": "leave-me-alone"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(custom))
    setup_mod.write_default_config(tmp_path)
    assert json.loads(path.read_text()) == custom


def test_write_default_config_overwrites_when_force(setup_mod, tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}")
    setup_mod.write_default_config(tmp_path, force=True)
    data = json.loads(path.read_text())
    assert data["indexing_model"] == "zo:openai/gpt-5.4-mini"


def test_service_registration_params_have_required_keys(setup_mod) -> None:
    params = setup_mod.SERVICE_REGISTRATION_PARAMS
    for key in ("label", "mode", "entrypoint", "working_directory", "environment", "description"):
        assert key in params, f"missing key: {key}"
    assert params["label"] == "sec-indexer"
    assert params["mode"] == "process"
    assert params["entrypoint"] == "sec-indexer"
    assert "ZO_API_KEY" in params["environment"]


def test_default_config_lists_three_models(setup_mod) -> None:
    """Indexing default + fallback + reasoning — the three roles per ARCHITECTURE.md."""
    cfg = setup_mod.DEFAULT_CONFIG
    assert cfg["indexing_model"].startswith("zo:")
    assert cfg["indexing_fallback_model"].startswith("zo:")
    assert cfg["reasoning_model"].startswith("zo:")
    assert cfg["sec_user_agent"]


def test_repo_root_points_at_actual_repo(setup_mod) -> None:
    """Regression: parents[N] index must land on the repo root.

    Caught a parents[2] off-by-one during Phase A test on Zo (setup.py was
    looking for skills/lib instead of repo/lib). Asserting against multiple
    sibling files locks the resolution to the right level.
    """
    repo = setup_mod.REPO_ROOT
    assert (repo / "lib").is_dir(), f"REPO_ROOT/lib not a dir: {repo / 'lib'}"
    assert (repo / "skills").is_dir(), f"REPO_ROOT/skills not a dir: {repo / 'skills'}"
    assert (repo / "ARCHITECTURE.md").is_file(), f"missing ARCHITECTURE.md at {repo}"


def test_lib_dir_resolves_to_real_library(setup_mod) -> None:
    """LIB_DIR must contain the ai_buffett_zo package and pyproject.toml."""
    lib = setup_mod.LIB_DIR
    assert lib.is_dir(), f"LIB_DIR does not exist: {lib}"
    assert (lib / "ai_buffett_zo" / "__init__.py").is_file()
    assert (lib / "pyproject.toml").is_file()
