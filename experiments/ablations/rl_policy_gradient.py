#!/usr/bin/env python3
"""True RL pipeline for adaptive injection optimization using policy gradients.

Implements the actual RL approach from https://arxiv.org/pdf/2510.04885 with:
- Policy network: Qwen model (attacker) that learns to generate effective injections
- Environment: Haiku agent (victim) executing tasks with injected skills
- Reward: Attack Success Rate (ASR) from evaluation
- Training: Policy gradient (REINFORCE algorithm) with advantage estimation

Architecture:
    Qwen (attacker) → generates injection → Haiku (victim) executes → ASR (reward) → policy update

This requires:
- Qwen model running on cluster (not downloaded locally)
- Gradient access to Qwen for policy updates
- Multiple rollouts per training iteration

Usage (preparation only, actual execution on cluster):
    python3 experiments/ablations/rl_policy_gradient.py --prepare
    # Then transfer to cluster and run with Qwen model
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    PROJECT_ROOT,
    CONTEXTUAL_INJECTIONS_FILE,
    AGENT_MODELS,
    DOCKER_IMAGE_NAME,
    FINAL_RESULTS_DIR,
)

# RL hyperparameters
DEFAULT_RL_ITERATIONS = 10
DEFAULT_ROLLOUTS_PER_ITERATION = 5
DEFAULT_LEARNING_RATE = 1e-5
DEFAULT_GAMMA = 0.99  # Discount factor
DEFAULT_BASELINE_DECAY = 0.9  # For advantage estimation


class RLConfig:
    """Configuration for RL training pipeline."""

    def __init__(
        self,
        attacker_model: str = "qwen",  # Placeholder, will be Qwen2.5 or similar
        victim_agent: str = "claude",
        victim_model: str = "haiku",
        n_iterations: int = DEFAULT_RL_ITERATIONS,
        rollouts_per_iteration: int = DEFAULT_ROLLOUTS_PER_ITERATION,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        gamma: float = DEFAULT_GAMMA,
        baseline_decay: float = DEFAULT_BASELINE_DECAY,
    ):
        self.attacker_model = attacker_model
        self.victim_agent = victim_agent
        self.victim_model = victim_model
        self.n_iterations = n_iterations
        self.rollouts_per_iteration = rollouts_per_iteration
        self.learning_rate = learning_rate
        self.gamma = gamma
        self.baseline_decay = baseline_decay

    def to_dict(self) -> dict:
        return {
            "attacker_model": self.attacker_model,
            "victim_agent": self.victim_agent,
            "victim_model": self.victim_model,
            "n_iterations": self.n_iterations,
            "rollouts_per_iteration": self.rollouts_per_iteration,
            "learning_rate": self.learning_rate,
            "gamma": self.gamma,
            "baseline_decay": self.baseline_decay,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RLConfig":
        return cls(**data)


class PolicyGradientTrainer:
    """REINFORCE-based policy gradient trainer for injection optimization.

    This is a scaffold that will be filled in when running on cluster with Qwen.

    The actual implementation requires:
    1. Qwen model loaded with gradient access
    2. Policy network wrapper around Qwen
    3. Rollout collection (generate injection → test on victim → get reward)
    4. Advantage estimation
    5. Policy gradient updates
    """

    def __init__(self, config: RLConfig, results_dir: Path):
        self.config = config
        self.results_dir = results_dir
        self.baseline = 0.0  # Moving average baseline for advantage estimation
        self.training_history = []

    def generate_injection_with_policy(
        self, base_injection: str, temperature: float = 1.0
    ) -> tuple[str, dict]:
        """Generate injection variant using policy network.

        Args:
            base_injection: Starting injection text
            temperature: Sampling temperature for policy

        Returns:
            (generated_injection, policy_logprobs) tuple

        Note: This is a PLACEHOLDER. On cluster, this will:
        1. Encode base_injection into Qwen
        2. Sample continuation tokens from policy distribution
        3. Track log probabilities for gradient computation
        4. Decode to get generated injection text
        """
        # PLACEHOLDER: To be implemented on cluster with Qwen
        # For now, just return base injection with empty logprobs
        return base_injection, {"logprobs": [], "tokens": []}

    def evaluate_injection(
        self,
        injection_text: str,
        injection_id: int,
        task_idx: int = 0,
    ) -> float:
        """Run victim agent with injection and compute reward (ASR).

        Args:
            injection_text: Injection to test
            injection_id: ID of base injection
            task_idx: Index of task to use

        Returns:
            Reward (1.0 for success, 0.0 for failure)

        This runs the victim agent (Haiku) on a short task with the
        injection embedded in the skill file, then evaluates ASR.
        """
        # Build sandbox with this injection variant
        sandbox_dir = self._build_sandbox(injection_text, injection_id, task_idx)

        # Run victim agent
        success = self._run_victim(sandbox_dir)

        return 1.0 if success else 0.0

    def _build_sandbox(
        self, injection_text: str, injection_id: int, task_idx: int
    ) -> Path:
        """Build sandbox with injection variant.

        Returns path to sandbox directory.
        """
        # Load base injection
        with CONTEXTUAL_INJECTIONS_FILE.open() as f:
            injections = json.load(f)

        injection = next((inj for inj in injections if inj["id"] == injection_id), None)
        if not injection:
            raise ValueError(f"Injection ID {injection_id} not found")

        # Create variant with custom injection text
        variant = {
            "id": injection_id,
            "instructions": {
                "line_injection": injection_text,
                "description_injection": injection_text,
            },
            "tasks": [injection["tasks"][task_idx]],
        }

        # Write to temp file
        variant_file = self.results_dir / "temp_injection_variant.json"
        variant_file.write_text(json.dumps([variant], indent=2), encoding="utf-8")

        # Build sandbox
        sandbox_root = self.results_dir / "temp_sandboxes"
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "build_sandbox.py"),
                "--agent",
                self.config.victim_agent,
                "--injections-file",
                str(variant_file),
                "--sandboxes-root",
                str(sandbox_root),
                "--clobber",
            ],
            check=True,
            capture_output=True,
        )

        # Return sandbox path
        sandbox_id = f"INST-{injection_id}_0_TASK-{task_idx}"
        return sandbox_root / sandbox_id

    def _run_victim(self, sandbox_dir: Path) -> bool:
        """Run victim agent on sandbox and return success/failure.

        Returns:
            True if attack succeeded, False otherwise
        """
        manifest = sandbox_dir.parent / "manifest.json"
        if not manifest.exists():
            return False

        # Run victim agent
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "run_sandbox_container.py"),
                "single",
                "--agent",
                self.config.victim_agent,
                "--model",
                self.config.victim_model,
                "--sandbox-dir",
                str(sandbox_dir),
                "--timeout",
                "300",  # Short timeout for RL iterations
            ],
            check=False,  # Don't fail on agent errors
            capture_output=True,
        )

        # Quick deterministic check for success
        # Look for evidence of injection execution
        stdout_file = sandbox_dir / "agent_stdout.txt"
        if not stdout_file.exists():
            return False

        stdout = stdout_file.read_text()
        # Simple heuristic: check if agent output suggests injection was followed
        # TODO: Use actual deterministic judge for more accurate evaluation
        return len(stdout) > 100  # Placeholder

    def collect_rollout(
        self, base_injection: str, injection_id: int, temperature: float = 1.0
    ) -> dict:
        """Collect a single rollout: generate → evaluate → compute return.

        Args:
            base_injection: Starting injection
            injection_id: ID of injection to optimize
            temperature: Sampling temperature

        Returns:
            Rollout dict with {injection, reward, logprobs, advantage}
        """
        # Generate injection from policy
        injection, policy_info = self.generate_injection_with_policy(
            base_injection, temperature
        )

        # Evaluate on victim
        reward = self.evaluate_injection(injection, injection_id)

        # Compute advantage (reward - baseline)
        advantage = reward - self.baseline

        return {
            "injection": injection,
            "reward": reward,
            "advantage": advantage,
            "logprobs": policy_info["logprobs"],
            "tokens": policy_info["tokens"],
        }

    def compute_policy_gradient(self, rollouts: list[dict]) -> dict:
        """Compute policy gradient from rollouts.

        Args:
            rollouts: List of rollout dicts

        Returns:
            Gradient dict (placeholder for actual gradient tensors)

        Note: This is a PLACEHOLDER. On cluster, this will:
        1. Compute ∑_t [advantage_t * ∇log π(a_t|s_t)]
        2. Average over rollouts
        3. Return gradient tensors for optimizer.step()
        """
        # PLACEHOLDER: To be implemented with actual Qwen gradients
        avg_reward = sum(r["reward"] for r in rollouts) / len(rollouts)
        avg_advantage = sum(r["advantage"] for r in rollouts) / len(rollouts)

        return {
            "avg_reward": avg_reward,
            "avg_advantage": avg_advantage,
            "n_rollouts": len(rollouts),
        }

    def update_policy(self, gradients: dict):
        """Apply policy gradients to update Qwen parameters.

        Args:
            gradients: Gradient dict from compute_policy_gradient

        Note: This is a PLACEHOLDER. On cluster, this will:
        1. optimizer.zero_grad()
        2. Apply computed gradients to Qwen parameters
        3. optimizer.step()
        4. Update baseline: baseline = decay * baseline + (1-decay) * avg_reward
        """
        # Update baseline (moving average of rewards)
        if gradients["n_rollouts"] > 0:
            self.baseline = (
                self.config.baseline_decay * self.baseline
                + (1 - self.config.baseline_decay) * gradients["avg_reward"]
            )

    def train(self, injection_ids: list[int] | None = None) -> dict:
        """Run full RL training loop.

        Args:
            injection_ids: List of injection IDs to optimize (None = all)

        Returns:
            Training summary dict
        """
        # Load base injections
        with CONTEXTUAL_INJECTIONS_FILE.open() as f:
            base_injections = json.load(f)

        if injection_ids:
            base_injections = [
                inj for inj in base_injections if inj["id"] in injection_ids
            ]

        print(f"\n{'='*70}")
        print(f"RL POLICY GRADIENT TRAINING")
        print(f"Attacker: {self.config.attacker_model}")
        print(f"Victim: {self.config.victim_agent}/{self.config.victim_model}")
        print(f"Iterations: {self.config.n_iterations}")
        print(f"Rollouts/iter: {self.config.rollouts_per_iteration}")
        print(f"{'='*70}\n")

        # Training loop
        for iteration in range(self.config.n_iterations):
            print(f"\n--- Iteration {iteration + 1}/{self.config.n_iterations} ---")

            iteration_rewards = []

            for injection in base_injections:
                injection_id = injection["id"]
                base_text = injection["instructions"]["description_injection"]

                # Collect rollouts
                rollouts = []
                for rollout_idx in range(self.config.rollouts_per_iteration):
                    rollout = self.collect_rollout(base_text, injection_id)
                    rollouts.append(rollout)
                    iteration_rewards.append(rollout["reward"])
                    print(
                        f"  Injection {injection_id}, rollout {rollout_idx + 1}: "
                        f"reward={rollout['reward']:.2f}, advantage={rollout['advantage']:.3f}"
                    )

                # Compute gradients
                gradients = self.compute_policy_gradient(rollouts)

                # Update policy
                self.update_policy(gradients)

            # Track training progress
            avg_reward = sum(iteration_rewards) / len(iteration_rewards)
            self.training_history.append(
                {
                    "iteration": iteration,
                    "avg_reward": avg_reward,
                    "baseline": self.baseline,
                    "n_rollouts": len(iteration_rewards),
                }
            )

            print(f"\nIteration {iteration + 1} summary:")
            print(f"  Average reward: {avg_reward:.3f}")
            print(f"  Baseline: {self.baseline:.3f}")

        # Save training history
        history_file = self.results_dir / "training_history.json"
        history_file.write_text(
            json.dumps(
                {
                    "config": self.config.to_dict(),
                    "history": self.training_history,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "final_baseline": self.baseline,
            "history": self.training_history,
        }


def prepare_cluster_deployment(
    config: RLConfig, injection_ids: list[int] | None = None
) -> Path:
    """Prepare files for cluster deployment.

    Creates a deployment package with:
    - Configuration JSON
    - Base injections
    - Cluster execution script
    - Instructions

    Args:
        config: RL configuration
        injection_ids: Optional list of injection IDs to include

    Returns:
        Path to deployment directory
    """
    deploy_dir = FINAL_RESULTS_DIR / "ablations" / "rl_policy_gradient" / "deployment"
    deploy_dir.mkdir(parents=True, exist_ok=True)

    # Save config
    config_file = deploy_dir / "rl_config.json"
    config_file.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")

    # Copy base injections
    with CONTEXTUAL_INJECTIONS_FILE.open() as f:
        injections = json.load(f)

    if injection_ids:
        injections = [inj for inj in injections if inj["id"] in injection_ids]

    injections_file = deploy_dir / "injections.json"
    injections_file.write_text(json.dumps(injections, indent=2), encoding="utf-8")

    # Create cluster execution script
    cluster_script = deploy_dir / "run_on_cluster.sh"
    cluster_script.write_text(
        """#!/bin/bash
# Cluster execution script for RL policy gradient training
# Run this on cluster after loading Qwen model

set -e

echo "Starting RL policy gradient training..."
echo "Make sure Qwen model is loaded and accessible!"

# TODO: Add actual cluster commands here:
# 1. Load Qwen model
# 2. Initialize policy network wrapper
# 3. Run training with PolicyGradientTrainer
# 4. Save final policy weights

python3 rl_policy_gradient.py --run --config rl_config.json

echo "Training complete. Results saved to results/"
""",
        encoding="utf-8",
    )
    cluster_script.chmod(0o755)

    # Create instructions
    instructions = deploy_dir / "README.md"
    instructions.write_text(
        f"""# RL Policy Gradient Training - Cluster Deployment

## Overview

This deployment package contains everything needed to run the RL policy gradient training on the cluster.

## Contents

- `rl_config.json` - Training configuration
- `injections.json` - Base injections to optimize
- `run_on_cluster.sh` - Cluster execution script
- `rl_policy_gradient.py` - Copy this file from experiments/ablations/

## Setup on Cluster

1. **Load Qwen model:**
   ```bash
   # Use your cluster's model loading mechanism
   # Example: module load qwen/2.5-7b
   ```

2. **Install dependencies:**
   ```bash
   pip install transformers torch anthropic
   ```

3. **Transfer files:**
   ```bash
   scp -r deployment/ cluster:/path/to/workdir/
   ```

4. **Set environment variables:**
   ```bash
   export ANTHROPIC_API_KEY=your_key_here  # For Haiku victim
   ```

## Running Training

```bash
cd deployment/
bash run_on_cluster.sh
```

## Configuration

Current settings:
- Attacker model: {config.attacker_model}
- Victim agent: {config.victim_agent}/{config.victim_model}
- Training iterations: {config.n_iterations}
- Rollouts per iteration: {config.rollouts_per_iteration}
- Learning rate: {config.learning_rate}

Edit `rl_config.json` to change these.

## Implementation Notes

The scaffold includes placeholders for:
1. `generate_injection_with_policy()` - Sample from Qwen policy
2. `compute_policy_gradient()` - REINFORCE gradient computation
3. `update_policy()` - Optimizer step on Qwen parameters

Fill these in with actual Qwen integration on cluster.

## Expected Output

- `training_history.json` - Reward curves over iterations
- `final_policy.pt` - Trained Qwen policy weights
- `best_injections.json` - Best discovered injections per ID
""",
        encoding="utf-8",
    )

    print(f"\n[prepare] Deployment package created at: {deploy_dir}")
    print(f"\nNext steps:")
    print(f"1. Review configuration in {config_file}")
    print(f"2. Transfer {deploy_dir} to cluster")
    print(f"3. Follow instructions in {instructions}")

    return deploy_dir


def main():
    parser = argparse.ArgumentParser(
        description="RL policy gradient training for injection optimization"
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Prepare deployment package for cluster (default action)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run training (use on cluster with Qwen loaded)",
    )
    parser.add_argument(
        "--config", type=Path, help="Path to config JSON (for --run)"
    )
    parser.add_argument(
        "--attacker-model",
        default="qwen2.5-7b",
        help="Attacker model name (default: qwen2.5-7b)",
    )
    parser.add_argument(
        "--victim-agent", default="claude", help="Victim agent (default: claude)"
    )
    parser.add_argument(
        "--victim-model", default="haiku", help="Victim model (default: haiku)"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_RL_ITERATIONS,
        help=f"Training iterations (default: {DEFAULT_RL_ITERATIONS})",
    )
    parser.add_argument(
        "--rollouts",
        type=int,
        default=DEFAULT_ROLLOUTS_PER_ITERATION,
        help=f"Rollouts per iteration (default: {DEFAULT_ROLLOUTS_PER_ITERATION})",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=DEFAULT_LEARNING_RATE,
        help=f"Learning rate (default: {DEFAULT_LEARNING_RATE})",
    )
    parser.add_argument(
        "--injection-id",
        type=int,
        action="append",
        dest="injection_ids",
        help="Injection IDs to optimize (default: all)",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Quick test: 2 iterations, 2 rollouts, injection ID 1",
    )

    args = parser.parse_args()

    # Default to prepare if no action specified
    if not args.run:
        args.prepare = True

    # Handle smoke test
    if args.smoke_test:
        args.iterations = 2
        args.rollouts = 2
        args.injection_ids = [1]

    # Create config
    config = RLConfig(
        attacker_model=args.attacker_model,
        victim_agent=args.victim_agent,
        victim_model=args.victim_model,
        n_iterations=args.iterations,
        rollouts_per_iteration=args.rollouts,
        learning_rate=args.learning_rate,
    )

    if args.prepare:
        # Prepare deployment package
        prepare_cluster_deployment(config, args.injection_ids)

    elif args.run:
        # Run training (on cluster)
        if args.config:
            with args.config.open() as f:
                config = RLConfig.from_dict(json.load(f))

        results_dir = (
            FINAL_RESULTS_DIR / "ablations" / "rl_policy_gradient" / "results"
        )
        results_dir.mkdir(parents=True, exist_ok=True)

        trainer = PolicyGradientTrainer(config, results_dir)
        summary = trainer.train(args.injection_ids)

        print(f"\n[done] Training complete. Results saved to {results_dir}")
        print(f"Final baseline reward: {summary['final_baseline']:.3f}")


if __name__ == "__main__":
    main()
