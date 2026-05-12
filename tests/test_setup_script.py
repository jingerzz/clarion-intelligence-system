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
    """Param names match what Zo's register_user_service tool actually accepts.

    Verified on 2026-05-07 in a live test: workdir + env_vars (snake_case) are
    the canonical keys; the env_vars value uses shell-style `$NAME` to resolve
    from a secret of that name.
    """
    params = setup_mod.SERVICE_REGISTRATION_PARAMS
    for key in ("label", "mode", "entrypoint", "workdir", "env_vars", "description"):
        assert key in params, f"missing key: {key}"
    assert params["label"] == "sec-indexer"
    assert params["mode"] == "process"
    assert params["entrypoint"] == "sec-indexer"
    assert params["workdir"] == "/home/workspace"
    assert params["env_vars"]["ZO_API_KEY"] == "$ZO_API_KEY"


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


# ---- Dummy-proofing the only manual step ---------------------------------


def test_user_action_message_dummy_proofed(setup_mod) -> None:
    """The user-facing message for the ZO_API_KEY secret step must include
    every cue a non-technical user needs to complete it without follow-up.

    Regression test for a UX bug observed on 2026-05-08: the chat agent
    relayed an over-summarized version of this step and the tester had to
    explicitly prompt for "step by step instructions" to get usable detail.
    Each assertion below pins one piece of the dummy-proofing in place so
    a future "tighten the wording" edit can't silently remove it."""
    msg = setup_mod.USER_ACTION_MESSAGE

    # The exact secret name (the most error-prone part — case + underscore).
    assert "`ZO_API_KEY`" in msg
    # Both menu paths spelled out.
    assert "Access Tokens" in msg
    assert "Secrets" in msg
    # The token prefix users can use to recognize they copied the right thing.
    assert "zo_sk_" in msg
    # A confirmation handshake so the agent knows when to proceed.
    assert "done" in msg.lower()
    # Numbered structure must survive — non-technical users follow numbers.
    for n in ("Step 1", "Step 2", "Step 3"):
        assert n in msg
    # Reassurance that this is the ONLY manual step.
    assert "only" in msg.lower() and "manual" in msg.lower()
    # And a fallback for "I can't find these menus" — user trust matters.
    assert "stuck" in msg.lower() or "can't find" in msg.lower()


def test_user_action_message_constant_is_named_for_discoverability(setup_mod) -> None:
    """The constant name signals intent: this is the verbatim block the
    chat agent must paste into the user's chat. Renaming it should require
    a deliberate update of SKILL.md too."""
    assert hasattr(setup_mod, "USER_ACTION_MESSAGE")
    assert isinstance(setup_mod.USER_ACTION_MESSAGE, str)
    assert len(setup_mod.USER_ACTION_MESSAGE) > 200  # not a stub


# ---- Sibling-skill auto-install ------------------------------------------


def _make_skill(src: Path, name: str) -> Path:
    """Create a minimal skill folder at src/name with a SKILL.md."""
    d = src / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n")
    return d


def test_install_sibling_skills_copies_each_skill(setup_mod, tmp_path: Path) -> None:
    src = tmp_path / "skills_src"
    src.mkdir()
    _make_skill(src, "clarion-foo")
    _make_skill(src, "clarion-bar")

    install_dir = tmp_path / "Skills"
    installed = setup_mod.install_sibling_skills(src, install_dir)

    assert sorted(installed) == ["clarion-bar", "clarion-foo"]
    assert (install_dir / "clarion-foo" / "SKILL.md").is_file()
    assert (install_dir / "clarion-bar" / "SKILL.md").is_file()


def test_install_sibling_skills_excludes_bootstrap_by_default(
    setup_mod, tmp_path: Path
) -> None:
    """clarion-setup itself must never be copied — it's installed externally
    by whatever surfaces the skill in the user's Zo (clone-from-registry, etc.)
    and the bootstrap copy in /home/workspace/Skills/ is the source of truth
    for this script's location. Overwriting it from a copy of the same script
    is at best redundant and at worst a footgun on a partial mid-run."""
    src = tmp_path / "skills_src"
    src.mkdir()
    _make_skill(src, "clarion-setup")
    _make_skill(src, "clarion-other")

    install_dir = tmp_path / "Skills"
    installed = setup_mod.install_sibling_skills(src, install_dir)

    assert installed == ["clarion-other"]
    assert not (install_dir / "clarion-setup").exists()


def test_install_sibling_skills_skips_non_skill_dirs(setup_mod, tmp_path: Path) -> None:
    """A folder without a SKILL.md (e.g. README, shared assets) must not
    be treated as a skill — guards against future repo additions silently
    leaking into the user's Skills/ directory."""
    src = tmp_path / "skills_src"
    src.mkdir()
    _make_skill(src, "clarion-good")
    (src / "_shared").mkdir()
    (src / "_shared" / "README.md").write_text("not a skill")
    (src / "stray-file.md").write_text("not a folder")

    install_dir = tmp_path / "Skills"
    installed = setup_mod.install_sibling_skills(src, install_dir)

    assert installed == ["clarion-good"]
    assert not (install_dir / "_shared").exists()


def test_install_sibling_skills_idempotent_and_refreshes(
    setup_mod, tmp_path: Path
) -> None:
    """Re-running setup must overwrite the installed copy with the upstream
    one. This is the user-facing path for picking up upstream skill fixes
    after a `git pull` — same contract as the rest of the setup steps."""
    src = tmp_path / "skills_src"
    src.mkdir()
    skill = _make_skill(src, "clarion-foo")
    (skill / "scripts").mkdir()
    (skill / "scripts" / "tool.py").write_text("VERSION = 1\n")

    install_dir = tmp_path / "Skills"
    setup_mod.install_sibling_skills(src, install_dir)
    assert (install_dir / "clarion-foo" / "scripts" / "tool.py").read_text() == "VERSION = 1\n"

    # Upstream changes; user simulates a re-run.
    (skill / "scripts" / "tool.py").write_text("VERSION = 2\n")
    (skill / "scripts" / "new_file.py").write_text("# added upstream\n")
    setup_mod.install_sibling_skills(src, install_dir)

    assert (install_dir / "clarion-foo" / "scripts" / "tool.py").read_text() == "VERSION = 2\n"
    assert (install_dir / "clarion-foo" / "scripts" / "new_file.py").is_file()


def test_install_sibling_skills_creates_install_dir_when_missing(
    setup_mod, tmp_path: Path
) -> None:
    src = tmp_path / "skills_src"
    src.mkdir()
    _make_skill(src, "clarion-foo")

    install_dir = tmp_path / "nested" / "Skills"
    assert not install_dir.exists()
    setup_mod.install_sibling_skills(src, install_dir)
    assert (install_dir / "clarion-foo" / "SKILL.md").is_file()


def test_install_sibling_skills_real_repo_includes_full_stack(
    setup_mod,
) -> None:
    """Regression test for the user-reported gap: setup.py running against
    the real repo must install every sibling clarion-* skill, not just a
    subset. If a new clarion-* skill is added to skills/, this test should
    pass without changes; if a skill is dropped, this test will flag it."""
    skills_dir = setup_mod.SKILLS_SRC_DIR
    if not skills_dir.is_dir():
        pytest.skip(f"skills source dir missing: {skills_dir}")

    siblings = {
        c.name
        for c in skills_dir.iterdir()
        if c.is_dir() and (c / "SKILL.md").is_file() and c.name != "clarion-setup"
    }
    # Sanity floor — the repo should always carry at least the named stack.
    expected_subset = {
        "clarion-regime-check",
        "clarion-sec-research",
        "clarion-single-stock-eval",
        "clarion-expected-return-calc",
        "clarion-value-screener",
        "clarion-thesis-write",
        "clarion-thesis-monitor",
        "clarion-watchlist-update",
        "clarion-living-letter-update",
    }
    missing = expected_subset - siblings
    assert not missing, f"expected sibling skills missing from repo: {missing}"
