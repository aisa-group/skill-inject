#!/usr/bin/env python3
"""Obvious injection experiment runner."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OBVIOUS_INJECTIONS_FILE, PROJECT_ROOT
from experiments._base import ExperimentRunner


class ObviousExperiment(ExperimentRunner):
    experiment_name = "obvious"
    injections_file = OBVIOUS_INJECTIONS_FILE
    default_timeout = 500

    def resolve_policies(self, args):
        # Obvious injections don't use safety policy variants
        return ["normal"]

    def evaluate(self, results_dir, args):
        subprocess.run([
            sys.executable,
            str(PROJECT_ROOT / "judges" / "obvious_judge.py"),
            str(results_dir),
            "--injections-file", str(self.injections_file),
            "--model", "gpt-5.1-codex-mini",
        ], check=True)


if __name__ == "__main__":
    ObviousExperiment().run()
