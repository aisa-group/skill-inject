#!/usr/bin/env python3
"""Contextual injection experiment runner."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CONTEXTUAL_INJECTIONS_FILE, PROJECT_ROOT
from experiments._base import ExperimentRunner


class ContextualExperiment(ExperimentRunner):
    experiment_name = "contextual"
    injections_file = CONTEXTUAL_INJECTIONS_FILE
    default_timeout = 700

    def evaluate(self, results_dir, args):
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "judges" / "contextual_judge.py"),
            str(results_dir),
            "--injections-file", str(self.injections_file),
            "--model", "sonnet",
        ]
        if not getattr(args, "no_evaluate_task", False):
            cmd.append("--evaluate-task")
        subprocess.run(cmd, check=True)

    def add_extra_args(self, parser):
        parser.add_argument("--no-evaluate-task", action="store_true",
                            help="Skip task completion (utility) evaluation")


if __name__ == "__main__":
    ContextualExperiment().run()
