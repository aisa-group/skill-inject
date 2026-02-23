"""Tests for config.py — paths, mappings, helpers, and cross-consistency."""
from __future__ import annotations

import pytest
from config import (
    PROJECT_ROOT,
    DATA_DIR,
    SKILL_ROOT,
    FINAL_RESULTS_DIR,
    AGENT_MODELS,
    SKILL_MAPPING,
    POLICY_CONFIGS,
    MODEL_CLI_MAP,
    AGENT_PARALLEL,
    CONTEXTUAL_INJECTIONS_FILE,
    OBVIOUS_INJECTIONS_FILE,
    get_skill_path,
    resolve_models,
)


class TestPaths:
    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()

    def test_data_dir_exists(self):
        assert DATA_DIR.exists()

    def test_skill_root_exists(self):
        assert SKILL_ROOT.exists()

    def test_final_results_dir_under_project(self):
        assert FINAL_RESULTS_DIR.parent == PROJECT_ROOT

    def test_injections_files_exist(self):
        assert CONTEXTUAL_INJECTIONS_FILE.exists(), f"Missing {CONTEXTUAL_INJECTIONS_FILE}"
        assert OBVIOUS_INJECTIONS_FILE.exists(), f"Missing {OBVIOUS_INJECTIONS_FILE}"


class TestAgentModels:
    def test_all_agents_have_models(self):
        for agent, models in AGENT_MODELS.items():
            assert len(models) > 0, f"Agent {agent} has no models"

    def test_model_entries_have_required_keys(self):
        for agent, models in AGENT_MODELS.items():
            for m in models:
                assert "model" in m, f"Missing 'model' key in {agent} models"
                assert "display_name" in m, f"Missing 'display_name' key in {agent} models"

    def test_no_duplicate_model_names_per_agent(self):
        for agent, models in AGENT_MODELS.items():
            names = [m["model"] for m in models]
            assert len(names) == len(set(names)), f"Duplicate model names in {agent}"


class TestSkillMapping:
    def test_mapping_not_empty(self):
        assert len(SKILL_MAPPING) > 0

    def test_get_skill_path_known(self):
        assert get_skill_path("pdf") == "document-skills/pdf"
        assert get_skill_path("git") == "git"

    def test_get_skill_path_unknown_returns_input(self):
        assert get_skill_path("nonexistent") == "nonexistent"

    def test_mapped_skills_exist(self):
        for skill_type, subdir in SKILL_MAPPING.items():
            path = SKILL_ROOT / subdir
            assert path.exists(), f"Skill path missing: {path} (mapped from '{skill_type}')"

    def test_each_skill_has_skill_md(self):
        for skill_type, subdir in SKILL_MAPPING.items():
            path = SKILL_ROOT / subdir / "SKILL.md"
            assert path.exists(), f"SKILL.md missing at {path} (skill '{skill_type}')"


class TestResolveModels:
    def test_resolve_all_claude(self):
        models = resolve_models("claude")
        assert len(models) >= 2

    def test_resolve_single_model(self):
        models = resolve_models("claude", "sonnet")
        assert len(models) == 1
        assert models[0]["model"] == "sonnet"

    def test_resolve_invalid_model_raises(self):
        with pytest.raises(ValueError, match="not found"):
            resolve_models("claude", "nonexistent-model")

    def test_resolve_each_agent_works(self):
        for agent in AGENT_MODELS:
            models = resolve_models(agent)
            assert len(models) > 0


class TestPolicyConfigs:
    def test_all_policies_present(self):
        assert "normal" in POLICY_CONFIGS
        assert "legitimizing" in POLICY_CONFIGS
        assert "warning" in POLICY_CONFIGS

    def test_policy_has_required_keys(self):
        for name, cfg in POLICY_CONFIGS.items():
            assert "safety_protocol" in cfg
            assert "suffix" in cfg


class TestModelCliMap:
    def test_not_empty(self):
        assert len(MODEL_CLI_MAP) > 0

    def test_entries_are_tuples(self):
        for model, val in MODEL_CLI_MAP.items():
            assert isinstance(val, tuple)
            assert len(val) == 2


class TestAgentParallel:
    def test_known_agents(self):
        assert "claude" in AGENT_PARALLEL
        assert "codex" in AGENT_PARALLEL
        assert "gemini" in AGENT_PARALLEL

    def test_values_are_positive_ints(self):
        for agent, n in AGENT_PARALLEL.items():
            assert isinstance(n, int) and n > 0, f"Invalid parallel count for {agent}: {n}"


# ---------------------------------------------------------------------------
# Cross-consistency checks
# ---------------------------------------------------------------------------

class TestCrossConsistency:
    def test_agent_parallel_covers_all_agents(self):
        for agent in AGENT_MODELS:
            assert agent in AGENT_PARALLEL, f"Agent {agent} in AGENT_MODELS but not AGENT_PARALLEL"

    def test_no_orphan_agent_parallel(self):
        for agent in AGENT_PARALLEL:
            assert agent in AGENT_MODELS, f"Agent {agent} in AGENT_PARALLEL but not AGENT_MODELS"
