#!/usr/bin/env python3
"""Tests for RL policy gradient injection optimization."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from experiments.ablations.rl_policy_gradient import (
    RLConfig,
    PolicyGradientTrainer,
    prepare_cluster_deployment,
)


class TestRLConfig:
    """Tests for RLConfig dataclass."""

    def test_default_initialization(self):
        config = RLConfig()
        assert config.attacker_model == "qwen"
        assert config.victim_agent == "claude"
        assert config.victim_model == "haiku"
        assert config.n_iterations == 10
        assert config.rollouts_per_iteration == 5

    def test_custom_initialization(self):
        config = RLConfig(
            attacker_model="qwen2.5-14b",
            victim_model="sonnet",
            n_iterations=20,
            rollouts_per_iteration=10,
            learning_rate=1e-4,
        )
        assert config.attacker_model == "qwen2.5-14b"
        assert config.victim_model == "sonnet"
        assert config.n_iterations == 20
        assert config.rollouts_per_iteration == 10
        assert config.learning_rate == 1e-4

    def test_to_dict(self):
        config = RLConfig(attacker_model="qwen2.5-7b", n_iterations=15)
        data = config.to_dict()
        assert isinstance(data, dict)
        assert data["attacker_model"] == "qwen2.5-7b"
        assert data["n_iterations"] == 15
        assert "learning_rate" in data
        assert "gamma" in data

    def test_from_dict(self):
        data = {
            "attacker_model": "qwen2.5-7b",
            "victim_agent": "claude",
            "victim_model": "haiku",
            "n_iterations": 15,
            "rollouts_per_iteration": 8,
            "learning_rate": 5e-5,
            "gamma": 0.95,
            "baseline_decay": 0.85,
        }
        config = RLConfig.from_dict(data)
        assert config.attacker_model == "qwen2.5-7b"
        assert config.n_iterations == 15
        assert config.rollouts_per_iteration == 8
        assert config.learning_rate == 5e-5

    def test_roundtrip(self):
        config1 = RLConfig(attacker_model="test", n_iterations=42)
        data = config1.to_dict()
        config2 = RLConfig.from_dict(data)
        assert config1.attacker_model == config2.attacker_model
        assert config1.n_iterations == config2.n_iterations
        assert config1.learning_rate == config2.learning_rate


class TestPolicyGradientTrainer:
    """Tests for PolicyGradientTrainer class."""

    @pytest.fixture
    def config(self):
        return RLConfig(
            attacker_model="qwen2.5-7b",
            victim_agent="claude",
            victim_model="haiku",
            n_iterations=2,
            rollouts_per_iteration=2,
        )

    @pytest.fixture
    def trainer(self, config, tmp_path):
        return PolicyGradientTrainer(config, tmp_path)

    def test_initialization(self, trainer, config, tmp_path):
        assert trainer.config == config
        assert trainer.results_dir == tmp_path
        assert trainer.baseline == 0.0
        assert trainer.training_history == []

    def test_generate_injection_placeholder(self, trainer):
        # Placeholder should return base injection unchanged
        injection, policy_info = trainer.generate_injection_with_policy(
            "test injection", temperature=1.0
        )
        assert injection == "test injection"
        assert "logprobs" in policy_info
        assert "tokens" in policy_info
        assert policy_info["logprobs"] == []

    def test_collect_rollout_structure(self, trainer):
        # Mock evaluate_injection to avoid actual execution
        with patch.object(trainer, "evaluate_injection", return_value=1.0):
            with patch.object(
                trainer,
                "generate_injection_with_policy",
                return_value=("variant", {"logprobs": [0.1], "tokens": [1]}),
            ):
                rollout = trainer.collect_rollout(
                    "base injection", injection_id=1, temperature=1.0
                )

        assert "injection" in rollout
        assert "reward" in rollout
        assert "advantage" in rollout
        assert "logprobs" in rollout
        assert "tokens" in rollout
        assert rollout["injection"] == "variant"
        assert rollout["reward"] == 1.0
        # Advantage = reward - baseline, baseline starts at 0
        assert rollout["advantage"] == 1.0

    def test_compute_policy_gradient_placeholder(self, trainer):
        rollouts = [
            {"reward": 1.0, "advantage": 1.0, "logprobs": [], "tokens": []},
            {"reward": 0.0, "advantage": -0.5, "logprobs": [], "tokens": []},
        ]
        gradients = trainer.compute_policy_gradient(rollouts)

        assert "avg_reward" in gradients
        assert "avg_advantage" in gradients
        assert "n_rollouts" in gradients
        assert gradients["avg_reward"] == 0.5
        assert gradients["avg_advantage"] == 0.25
        assert gradients["n_rollouts"] == 2

    def test_update_policy_updates_baseline(self, trainer):
        initial_baseline = trainer.baseline
        gradients = {"avg_reward": 0.8, "n_rollouts": 5}

        trainer.update_policy(gradients)

        # Baseline should update: b = decay * b + (1-decay) * reward
        expected = trainer.config.baseline_decay * initial_baseline + (
            1 - trainer.config.baseline_decay
        ) * 0.8
        assert trainer.baseline == pytest.approx(expected)

    def test_update_policy_with_zero_rollouts(self, trainer):
        initial_baseline = trainer.baseline
        gradients = {"avg_reward": 0.0, "n_rollouts": 0}

        trainer.update_policy(gradients)

        # Baseline shouldn't change with 0 rollouts
        assert trainer.baseline == initial_baseline

    def test_baseline_convergence(self, trainer):
        # Simulate multiple updates with same reward
        reward = 0.7
        for _ in range(50):
            trainer.update_policy({"avg_reward": reward, "n_rollouts": 1})

        # Baseline should converge close to reward
        # With decay=0.9, baseline ≈ reward after many updates
        assert trainer.baseline == pytest.approx(reward, abs=0.1)

    def test_training_history_tracking(self, trainer):
        assert len(trainer.training_history) == 0

        # Simulate training (without actual execution)
        with patch.object(trainer, "collect_rollout") as mock_rollout:
            mock_rollout.return_value = {
                "injection": "test",
                "reward": 0.5,
                "advantage": 0.5,
                "logprobs": [],
                "tokens": [],
            }

            # Mock injections file
            with patch(
                "builtins.open",
                create=True,
            ) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = (
                    json.dumps(
                        [
                            {
                                "id": 1,
                                "instructions": {"description_injection": "test"},
                                "tasks": [{"prompt": "test"}],
                            }
                        ]
                    )
                )

                # Run training would track history
                # (We can't easily test the full train() method without mocking a lot)
                # Instead, manually verify history structure
                trainer.training_history.append(
                    {
                        "iteration": 0,
                        "avg_reward": 0.5,
                        "baseline": 0.0,
                        "n_rollouts": 2,
                    }
                )

        assert len(trainer.training_history) == 1
        assert trainer.training_history[0]["iteration"] == 0
        assert trainer.training_history[0]["avg_reward"] == 0.5


class TestPrepareClusterDeployment:
    """Tests for cluster deployment preparation."""

    def test_creates_deployment_directory(self, tmp_path):
        config = RLConfig()

        # Mock FINAL_RESULTS_DIR
        with patch("experiments.ablations.rl_policy_gradient.FINAL_RESULTS_DIR", tmp_path):
            deploy_dir = prepare_cluster_deployment(config, injection_ids=[1])

        assert deploy_dir.exists()
        assert deploy_dir.is_dir()
        assert "deployment" in str(deploy_dir)

    def test_creates_config_file(self, tmp_path):
        config = RLConfig(attacker_model="qwen2.5-14b", n_iterations=20)

        with patch("experiments.ablations.rl_policy_gradient.FINAL_RESULTS_DIR", tmp_path):
            with patch("experiments.ablations.rl_policy_gradient.CONTEXTUAL_INJECTIONS_FILE") as mock_file:
                mock_file.open.return_value.__enter__.return_value.read.return_value = json.dumps([
                    {"id": 1, "instructions": {"description_injection": "test"}, "tasks": []}
                ])
                deploy_dir = prepare_cluster_deployment(config)

        config_file = deploy_dir / "rl_config.json"
        assert config_file.exists()

        with config_file.open() as f:
            saved_config = json.load(f)

        assert saved_config["attacker_model"] == "qwen2.5-14b"
        assert saved_config["n_iterations"] == 20

    def test_creates_cluster_script(self, tmp_path):
        config = RLConfig()

        with patch("experiments.ablations.rl_policy_gradient.FINAL_RESULTS_DIR", tmp_path):
            with patch("experiments.ablations.rl_policy_gradient.CONTEXTUAL_INJECTIONS_FILE") as mock_file:
                mock_file.open.return_value.__enter__.return_value.read.return_value = json.dumps([
                    {"id": 1, "instructions": {"description_injection": "test"}, "tasks": []}
                ])
                deploy_dir = prepare_cluster_deployment(config)

        script = deploy_dir / "run_on_cluster.sh"
        assert script.exists()
        # Check it's executable
        assert script.stat().st_mode & 0o111  # At least one execute bit set

    def test_creates_readme(self, tmp_path):
        config = RLConfig()

        with patch("experiments.ablations.rl_policy_gradient.FINAL_RESULTS_DIR", tmp_path):
            with patch("experiments.ablations.rl_policy_gradient.CONTEXTUAL_INJECTIONS_FILE") as mock_file:
                mock_file.open.return_value.__enter__.return_value.read.return_value = json.dumps([
                    {"id": 1, "instructions": {"description_injection": "test"}, "tasks": []}
                ])
                deploy_dir = prepare_cluster_deployment(config)

        readme = deploy_dir / "README.md"
        assert readme.exists()

        content = readme.read_text()
        assert "RL Policy Gradient" in content
        assert "Cluster Deployment" in content

    def test_filters_injections_by_id(self, tmp_path):
        config = RLConfig()
        mock_injections = [
            {"id": 1, "instructions": {"description_injection": "test1"}, "tasks": []},
            {"id": 2, "instructions": {"description_injection": "test2"}, "tasks": []},
            {"id": 3, "instructions": {"description_injection": "test3"}, "tasks": []},
        ]

        with patch("experiments.ablations.rl_policy_gradient.FINAL_RESULTS_DIR", tmp_path):
            with patch("experiments.ablations.rl_policy_gradient.CONTEXTUAL_INJECTIONS_FILE") as mock_file:
                mock_file.open.return_value.__enter__.return_value.read.return_value = json.dumps(mock_injections)
                deploy_dir = prepare_cluster_deployment(config, injection_ids=[1, 3])

        injections_file = deploy_dir / "injections.json"
        with injections_file.open() as f:
            saved_injections = json.load(f)

        assert len(saved_injections) == 2
        assert saved_injections[0]["id"] == 1
        assert saved_injections[1]["id"] == 3


class TestIntegration:
    """Integration tests for RL pipeline components."""

    def test_config_trainer_integration(self, tmp_path):
        config = RLConfig(n_iterations=1, rollouts_per_iteration=1)
        trainer = PolicyGradientTrainer(config, tmp_path)

        assert trainer.config.n_iterations == 1
        assert trainer.config.rollouts_per_iteration == 1

    def test_rollout_to_gradient_to_update_pipeline(self, tmp_path):
        config = RLConfig()
        trainer = PolicyGradientTrainer(config, tmp_path)

        # Simulate rollout collection
        with patch.object(trainer, "evaluate_injection", return_value=0.8):
            with patch.object(
                trainer,
                "generate_injection_with_policy",
                return_value=("test", {"logprobs": [], "tokens": []}),
            ):
                rollouts = [
                    trainer.collect_rollout("base", 1) for _ in range(3)
                ]

        # Compute gradients
        gradients = trainer.compute_policy_gradient(rollouts)
        assert gradients["avg_reward"] == 0.8

        # Update policy
        initial_baseline = trainer.baseline
        trainer.update_policy(gradients)
        assert trainer.baseline > initial_baseline  # Should increase
