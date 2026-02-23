#!/usr/bin/env python3
"""Utility baseline experiment: clean tasks with and without security policy.

This experiment measures task completion rates under two conditions:
1. No security policy (baseline)
2. Unified security policy (all warnings from contextual injections)

No injections are present in either condition. This establishes:
- Baseline utility for each model on each task
- Impact of security policy on utility when no attack is present
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    PROJECT_ROOT,
    AGENT_MODELS,
    AGENT_PARALLEL,
    DOCKER_IMAGE_NAME,
    FINAL_RESULTS_DIR,
    resolve_models,
)


class UtilityBaselineExperiment:
    experiment_name = "utility_baseline"
    default_timeout = 700

    def __init__(self):
        self.tasks_file = PROJECT_ROOT / "data" / "tasks.json"
        self.security_policy_file = PROJECT_ROOT / "data" / "unified_security_policy.md"

    def build_parser(self):
        import argparse
        p = argparse.ArgumentParser(
            description="Utility baseline: clean tasks with/without security policy"
        )
        p.add_argument("--agent", choices=list(AGENT_MODELS.keys()), required=True)
        p.add_argument("--model", default=None, help="Run only this model")
        p.add_argument("--condition", choices=["no_policy", "policy"],
                       help="Run only this condition (default: both)")
        p.add_argument("--parallel", type=int, default=None)
        p.add_argument("--timeout", type=int, default=self.default_timeout)
        p.add_argument("--skip-eval", action="store_true",
                       help="Skip evaluation after running agents")
        p.add_argument("--force", action="store_true",
                       help="Delete existing results and rerun everything")
        p.add_argument("--task-id", type=int,
                       help="Run only this task ID (for testing)")
        return p

    def ensure_docker_image(self):
        r = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE_NAME],
            capture_output=True,
        )
        if r.returncode != 0:
            print("[build] Docker image not found, building...")
            subprocess.run(
                ["bash", str(PROJECT_ROOT / "docker" / "build.sh")],
                check=True,
            )

    def results_dir_for(self, agent, model, condition):
        """Get final results directory for agent/model/condition."""
        agent_model = f"{agent}-{model}"
        return FINAL_RESULTS_DIR / self.experiment_name / agent_model / condition

    def build_sandboxes(self, agent, sandboxes_dir, condition, args):
        """Build sandboxes for the given condition."""
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_clean_sandboxes.py"),
            "--agent", agent,
            "--tasks-file", str(self.tasks_file),
            "--sandboxes-root", str(sandboxes_dir),
            "--clobber",
        ]

        # Add security policy for "policy" condition
        if condition == "policy":
            cmd += ["--security-policy", str(self.security_policy_file)]

        # Task ID filter for testing
        if args.task_id:
            cmd += ["--task-id", str(args.task_id)]

        print(f"\n[build] {condition}")
        subprocess.run(cmd, check=True)

    def run_agent(self, agent, model, sandboxes_dir, results_dir, parallel, timeout):
        """Run agent on sandboxes."""
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_sandbox_container.py"),
            "run",
            "--sandboxes-root", str(sandboxes_dir),
            "--results-dir", str(results_dir),
            "--agent", agent,
            "--model", model,
            "--parallel", str(parallel),
            "--timeout", str(timeout),
        ]

        print(f"[run] {agent} ({model}) on {sandboxes_dir.name}")
        subprocess.run(cmd, check=True)

    def evaluate(self, results_dir):
        """Evaluate results using contextual judge (task completion only)."""
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "judges" / "contextual_judge.py"),
            str(results_dir),
            "--model", "gpt-5.1-codex-mini",
            "--evaluate-task",
            "--no-evaluate-injection",  # No injections to evaluate
        ]

        print(f"[eval] {results_dir}")
        subprocess.run(cmd, check=True)

    def run_condition(self, agent, model, condition, args):
        """Run one condition (no_policy or policy) for a model."""
        # Set up directories
        results_dir = self.results_dir_for(agent, model, condition)
        sandboxes_dir = PROJECT_ROOT / "sandboxes" / self.experiment_name / agent / condition

        # Build sandboxes
        self.build_sandboxes(agent, sandboxes_dir, condition, args)

        # Run agents
        parallel = args.parallel if args.parallel else AGENT_PARALLEL.get(agent, 15)
        self.run_agent(agent, model, sandboxes_dir, results_dir, parallel, args.timeout)

        # Evaluate
        if not args.skip_eval:
            self.evaluate(results_dir)

    def run(self):
        parser = self.build_parser()
        args = parser.parse_args()

        # Check Docker
        self.ensure_docker_image()

        # Resolve models
        agent = args.agent
        model_dicts = resolve_models(agent, args.model)
        model_names = [m["model"] for m in model_dicts]

        # Resolve conditions
        conditions = [args.condition] if args.condition else ["no_policy", "policy"]

        print(f"\n{'='*60}")
        print(f"  Utility Baseline Experiment")
        print(f"{'='*60}")
        print(f"Agent: {agent}")
        print(f"Models: {', '.join(model_names)}")
        print(f"Conditions: {', '.join(conditions)}")
        print(f"Parallel: {args.parallel or AGENT_PARALLEL.get(agent, 15)}")
        print(f"{'='*60}\n")

        # Run experiments
        for model_name in model_names:
            for condition in conditions:
                print(f"\n{'='*60}")
                print(f"  {agent.upper()}: {model_name} / {condition}")
                print(f"{'='*60}")

                try:
                    self.run_condition(agent, model_name, condition, args)
                except Exception as e:
                    print(f"[error] {agent} / {model_name} / {condition}: {e}")
                    if args.task_id:  # Fail fast in test mode
                        raise

        print(f"\n{'='*60}")
        print(f"  Utility Baseline Experiment Complete")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    UtilityBaselineExperiment().run()
