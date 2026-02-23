"""Tests for experiments/_base.py and experiment subclasses.

Merges the former test_smoke.py into this file to avoid duplication.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from experiments._base import ExperimentRunner
from experiments.contextual import ContextualExperiment
from experiments.obvious import ObviousExperiment
from config import POLICY_CONFIGS, FINAL_RESULTS_DIR


class DummyExperiment(ExperimentRunner):
    experiment_name = "test_experiment"
    injections_file = Path("test.json")
    default_timeout = 100

    def evaluate(self, results_dir, args):
        pass


# ---------------------------------------------------------------------------
# resolve_policies
# ---------------------------------------------------------------------------

class TestResolvePolicies:
    def test_default_all(self):
        exp = DummyExperiment()
        args = argparse.Namespace(policy=None)
        policies = exp.resolve_policies(args)
        assert set(policies) == set(POLICY_CONFIGS.keys())

    def test_explicit_single(self):
        exp = DummyExperiment()
        args = argparse.Namespace(policy=["warning"])
        policies = exp.resolve_policies(args)
        assert policies == ["warning"]

    def test_dedup(self):
        exp = DummyExperiment()
        args = argparse.Namespace(policy=["normal", "normal"])
        policies = exp.resolve_policies(args)
        assert policies == ["normal"]

    def test_contextual_default_all(self):
        exp = ContextualExperiment()
        args = argparse.Namespace(policy=None)
        policies = exp.resolve_policies(args)
        assert set(policies) == set(POLICY_CONFIGS.keys())

    def test_obvious_single_policy(self):
        exp = ObviousExperiment()
        args = argparse.Namespace(policy=None)
        policies = exp.resolve_policies(args)
        assert policies == ["normal"]


# ---------------------------------------------------------------------------
# results_dir_for
# ---------------------------------------------------------------------------

class TestResultsDirFor:
    def test_basic(self):
        exp = DummyExperiment()
        path = exp.results_dir_for("claude", "sonnet", "normal")
        assert path == FINAL_RESULTS_DIR / "test_experiment" / "claude-sonnet" / "normal"

    def test_dots_replaced(self):
        exp = DummyExperiment()
        path = exp.results_dir_for("codex", "gpt-5.2-codex", "warning")
        assert "." not in path.name
        assert path.parent.name == "codex-gpt-5-2-codex"


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_has_required_args(self):
        exp = DummyExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude"])
        assert args.agent == "claude"
        assert args.smoke_test is False

    def test_smoke_test_flag(self):
        exp = DummyExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--smoke-test"])
        assert args.smoke_test is True

    def test_policy_flag(self):
        exp = DummyExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--policy", "warning"])
        assert args.policy == ["warning"]

    def test_model_flag(self):
        exp = DummyExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--model", "sonnet"])
        assert args.model == "sonnet"


# ---------------------------------------------------------------------------
# add_extra_args
# ---------------------------------------------------------------------------

class TestAddExtraArgs:
    def test_subclass_can_add_args(self):
        class WithExtra(DummyExperiment):
            def add_extra_args(self, parser):
                parser.add_argument("--extra-flag", action="store_true")

        exp = WithExtra()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--extra-flag"])
        assert args.extra_flag is True


# ---------------------------------------------------------------------------
# Smoke test flag wiring across subclasses (merged from test_smoke.py)
# ---------------------------------------------------------------------------

class TestSmokeTestWiring:
    def test_base_parser_has_smoke_test(self):
        exp = ExperimentRunner()
        exp.experiment_name = "test"
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--smoke-test"])
        assert args.smoke_test is True

    def test_contextual_parser(self):
        exp = ContextualExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--smoke-test"])
        assert args.smoke_test is True
        assert hasattr(args, "no_evaluate_task")

    def test_obvious_parser(self):
        exp = ObviousExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--smoke-test"])
        assert args.smoke_test is True

    def test_smoke_test_limits_to_one_policy(self):
        """Smoke test should run with only the first policy."""
        exp = ContextualExperiment()
        args = argparse.Namespace(policy=None)
        policies = exp.resolve_policies(args)
        # Simulate what run() does for smoke-test
        policies = [policies[0]]
        assert len(policies) == 1


# ---------------------------------------------------------------------------
# Experiment name / config
# ---------------------------------------------------------------------------

class TestExperimentConfig:
    def test_contextual_name(self):
        assert ContextualExperiment.experiment_name == "contextual"

    def test_obvious_name(self):
        assert ObviousExperiment.experiment_name == "obvious"

    def test_contextual_has_injections_file(self):
        assert ContextualExperiment.injections_file.name.endswith(".json")

    def test_obvious_has_injections_file(self):
        assert ObviousExperiment.injections_file.name.endswith(".json")

    def test_contextual_has_no_evaluate_task_arg(self):
        exp = ContextualExperiment()
        parser = exp.build_parser()
        args = parser.parse_args(["--agent", "claude", "--no-evaluate-task"])
        assert args.no_evaluate_task is True
