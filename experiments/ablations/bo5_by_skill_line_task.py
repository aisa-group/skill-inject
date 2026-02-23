#!/usr/bin/env python3
"""Best-of-5 by Skill, Line & Task ablation for obvious injections (OLD).

For each of 5 runs, a different task variant (line_num / injection_prefix)
from the injection's tasks list is used, testing whether injection position
affects attack success rate. Each run varies skill, line position, AND task.

Superseded by bo5_byline.py which uses obvious_injections_byline.json
(same task per injection, only line position varies).

Usage:
    python3 experiments/ablations/bo5_by_skill_line_task.py --agent claude
    python3 experiments/ablations/bo5_by_skill_line_task.py --agent claude --model sonnet --smoke-test
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    PROJECT_ROOT,
    OBVIOUS_INJECTIONS_FILE,
    AGENT_MODELS,
    AGENT_PARALLEL,
    DOCKER_IMAGE_NAME,
    FINAL_RESULTS_DIR,
    resolve_models,
)

N_RUNS = 5


def create_variant_injections(
    injections: list[dict], task_index: int,
    injection_ids: list[int] | None = None,
) -> list[dict]:
    """Return a copy of injections with only the task at *task_index*."""
    out = []
    for inj in injections:
        if injection_ids and inj["id"] not in injection_ids:
            continue
        variant = copy.deepcopy(inj)
        tasks = variant.get("tasks", [])
        if tasks:
            variant["tasks"] = [tasks[task_index % len(tasks)]]
        out.append(variant)
    return out


def build_for_run(
    agent: str, run_idx: int, run_dir: Path,
    injections: list[dict],
    injection_ids: list[int] | None = None,
    description_injection: bool = False,
) -> tuple[Path, Path]:
    """Build sandboxes for a specific run. Returns (agent_dir, variant_file)."""
    variant_file = run_dir / f"injections_run{run_idx}.json"
    variant_file.write_text(
        json.dumps(create_variant_injections(injections, run_idx - 1, injection_ids), indent=2),
        encoding="utf-8",
    )

    agent_dir = run_dir / f"{agent}_run{run_idx}"
    if agent_dir.exists():
        subprocess.run(["rm", "-rf", str(agent_dir)], check=True)

    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "build_sandbox.py"),
        "--agent", agent,
        "--injections-file", str(variant_file),
        "--sandboxes-root", str(agent_dir),
        "--clobber",
    ]
    if description_injection:
        cmd.append("--description-injection")
    print(f"\n[run {run_idx}] Building sandboxes (task variant {run_idx - 1})...")
    subprocess.run(cmd, check=True)
    return agent_dir, variant_file


def run_and_evaluate(
    agent: str, model: str, run_idx: int,
    agent_dir: Path, variant_file: Path,
    results_dir: Path, parallel: int, timeout: int,
) -> dict:
    """Run agent + evaluate one run. Returns evaluation JSON."""
    status_log = results_dir.parent / f"status_{model}_{run_idx}.jsonl"
    subprocess.run([
        sys.executable, str(PROJECT_ROOT / "scripts" / "run_sandbox_container.py"), "run",
        "--agent", agent, "--model", model,
        "--sandboxes-root", str(agent_dir),
        "--results-dir", str(results_dir),
        "--timeout", str(timeout),
        "--parallel", str(parallel),
        "--status-log", str(status_log),
    ], check=True)

    subprocess.run([
        sys.executable, str(PROJECT_ROOT / "judges" / "obvious_judge.py"),
        str(results_dir),
        "--injections-file", str(variant_file),
        "--model", "haiku",
    ], check=True)

    eval_file = results_dir / "evaluation_llmjudge_haiku.json"
    if eval_file.exists():
        with eval_file.open() as f:
            return json.load(f)
    return {"results": []}


def aggregate(all_runs: list[dict], n_runs: int) -> dict:
    """Aggregate per-injection Bo5 results."""
    per_injection: dict[int, dict] = defaultdict(lambda: {"successes": 0, "runs": n_runs})
    for run_data in all_runs:
        succeeded = set()
        for r in run_data.get("data", {}).get("results", []):
            if r.get("score") == "attack_success":
                succeeded.add(r["injection_id"])
        for iid in succeeded:
            per_injection[iid]["successes"] += 1

    return dict(per_injection)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Best-of-5 by Line ablation (obvious)")
    parser.add_argument("--agent", choices=list(AGENT_MODELS.keys()), required=True)
    parser.add_argument("--model", help="Run only this model")
    parser.add_argument("--injection-id", type=int, action="append")
    parser.add_argument("--description-injection", action="store_true")
    parser.add_argument("--timeout", type=int, default=500)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run injection ID 1, 1 run, sequential")
    args = parser.parse_args()

    agent = args.agent
    models = resolve_models(agent, args.model)
    parallel = AGENT_PARALLEL.get(agent, 10)

    with OBVIOUS_INJECTIONS_FILE.open() as f:
        injections = json.load(f)

    injection_ids = args.injection_id
    n_runs = N_RUNS
    if args.smoke_test:
        injection_ids = [1]
        n_runs = 1
        parallel = 1

    # Ensure Docker image exists
    r = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE_NAME], capture_output=True)
    if r.returncode != 0:
        subprocess.run(["bash", str(PROJECT_ROOT / "docker" / "build.sh")], check=True)

    results_base = FINAL_RESULTS_DIR / "ablations" / "bo5_by_skill_line_task"

    for mcfg in models:
        model = mcfg["model"]
        display = mcfg["display_name"]
        slug = f"{agent}-{model}".replace(".", "-")
        run_dir = results_base / slug
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'#'*60}")
        print(f"# {display} — {n_runs} runs (varying line positions)")
        print(f"{'#'*60}")

        all_runs = []
        for ri in range(1, n_runs + 1):
            ad, vf = build_for_run(agent, ri, run_dir, injections,
                                   injection_ids, args.description_injection)
            rd = run_dir / f"run-{ri}"
            rd.mkdir(parents=True, exist_ok=True)
            data = run_and_evaluate(agent, model, ri, ad, vf, rd, parallel, args.timeout)
            all_runs.append({"run": ri, "data": data})

        per_inj = aggregate(all_runs, n_runs)
        summary = {
            "agent": agent, "model": model, "n_runs": n_runs,
            "per_injection": per_inj, "all_runs": all_runs,
        }
        out = run_dir / "aggregated_results_byline.json"
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved aggregated results to {out}")

    print("\n[done] Bo5 by skill, line & task ablation complete.")


if __name__ == "__main__":
    main()
