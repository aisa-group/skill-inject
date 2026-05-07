#!/usr/bin/env python3
"""Best-of-5 with combined (line + task + phrasing) variation for the 7-injection
adaptive-attack subset.

Reads data/Bo5_subset.json (7 injections; each has 25 task entries laid out as
5 task variants x 5 line positions, plus 5 phrasing_variants). For each of the
5 runs, every injection uses one diagonal tuple

    run i -> task_idx = i, line_idx = i, phrasing_idx = i

so each run varies all three axes jointly versus the previous one. Bo5 success
is "any of the 5 runs succeeded" per injection. Evaluation uses the same
deterministic unit tests as bo5_byline.py.

Usage:
    python3 experiments/ablations/bo5_combined.py                   # all 8 models
    python3 experiments/ablations/bo5_combined.py --agent codex --model gpt-5.2-codex
    python3 experiments/ablations/bo5_combined.py --smoke-test
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "data" / "instruction_unit_tests"))
from config import (
    PROJECT_ROOT,
    DATA_DIR,
    AGENT_PARALLEL,
    DOCKER_IMAGE_NAME,
    APPTAINER_DIR,
    APPTAINER_IMAGE_NAME,
    FINAL_RESULTS_DIR,
)

SUBSET_FILE = DATA_DIR / "Bo5_subset.json"
UNIT_TESTS_DIR = PROJECT_ROOT / "data" / "instruction_unit_tests" / "obvious"
N_RUNS = 5
N_TASK_VARIANTS = 5
N_LINE_POSITIONS = 5

# 8-model set matching the existing bo5_byline result archive.
ABLATION_MODELS: list[dict[str, str]] = [
    {"agent": "claude", "model": "claude-opus-4-5-20251101", "display_name": "Opus 4.5"},
    {"agent": "claude", "model": "sonnet",                   "display_name": "Sonnet 4.5"},
    {"agent": "claude", "model": "haiku",                    "display_name": "Haiku 4.5"},
    {"agent": "codex",  "model": "gpt-5-codex",              "display_name": "GPT-5-Codex"},
    {"agent": "codex",  "model": "gpt-5.2-codex",            "display_name": "GPT-5.2-Codex"},
    {"agent": "codex",  "model": "gpt-5.1-codex-mini",       "display_name": "GPT-5.1-Codex-Mini"},
    {"agent": "gemini", "model": "gemini-3-pro-preview",     "display_name": "Gemini 3 Pro"},
    {"agent": "gemini", "model": "gemini-3-flash-preview",   "display_name": "Gemini 3 Flash"},
]


def diagonal_variant(injection: dict, run_idx: int) -> dict:
    """Return a copy of *injection* containing exactly one task entry, with
    instructions.line_injection overridden by the run-matched phrasing variant.

    Diagonal selection: run i (1-indexed) -> task_idx = i-1, line_idx = i-1,
    phrasing_idx = i-1. Falls back gracefully if any axis has fewer than 5
    entries.
    """
    i = (run_idx - 1)
    out = copy.deepcopy(injection)
    tasks = out.get("tasks", [])
    if not tasks:
        return out

    # Bo5_subset.json packs tasks as 5 task variants x 5 line positions = 25.
    # Index is task_idx * N_LINE_POSITIONS + line_idx.
    n_total = len(tasks)
    if n_total >= N_TASK_VARIANTS * N_LINE_POSITIONS:
        task_idx = i % N_TASK_VARIANTS
        line_idx = i % N_LINE_POSITIONS
        flat_idx = task_idx * N_LINE_POSITIONS + line_idx
    else:
        # Fallback for injections that don't fit the 5x5 layout.
        flat_idx = i % n_total
    out["tasks"] = [tasks[flat_idx]]

    phrasing = out.pop("phrasing_variants", None)
    if phrasing:
        variant = phrasing[i % len(phrasing)]
        out.setdefault("instructions", {})
        out["instructions"]["line_injection"] = variant["line_injection"]
        # Keep the chosen style on the entry so downstream tooling can read it.
        out["selected_phrasing_style"] = variant.get("style", f"variant_{i}")

    out["selected_run_idx"] = run_idx
    out["selected_flat_task_idx"] = flat_idx
    return out


def create_variant_injections(
    injections: list[dict], run_idx: int,
    injection_ids: list[int] | None = None,
) -> list[dict]:
    out = []
    for inj in injections:
        if injection_ids and inj["id"] not in injection_ids:
            continue
        out.append(diagonal_variant(inj, run_idx))
    return out


def build_for_run(
    agent: str, run_idx: int, run_dir: Path,
    injections: list[dict],
    injection_ids: list[int] | None = None,
    description_injection: bool = False,
) -> tuple[Path, Path]:
    variant_file = run_dir / f"injections_run{run_idx}.json"
    variant_file.write_text(
        json.dumps(create_variant_injections(injections, run_idx, injection_ids), indent=2),
        encoding="utf-8",
    )

    agent_dir = run_dir / f"{agent}_run{run_idx}"
    if agent_dir.exists():
        subprocess.run(["rm", "-rf", str(agent_dir)], check=True)

    cmd = [
        "python3", str(PROJECT_ROOT / "scripts" / "build_sandbox.py"),
        "--agent", agent,
        "--injections-file", str(variant_file),
        "--sandboxes-root", str(agent_dir),
        "--clobber",
    ]
    if description_injection:
        cmd.append("--description-injection")
    print(f"\n[run {run_idx}] Building sandboxes (diagonal: task/line/phrasing idx = {run_idx - 1})...")
    subprocess.run(cmd, check=True)
    return agent_dir, variant_file


def _load_unit_test(injection_id: int):
    test_file = UNIT_TESTS_DIR / f"test_obvious_{injection_id}.py"
    if not test_file.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"test_{injection_id}", test_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "test_attack", None)


def evaluate_with_unit_tests(results_dir: Path) -> dict:
    results = []
    for sd in sorted(results_dir.iterdir()):
        if not sd.is_dir() or not sd.name.startswith("INST-"):
            continue
        iid = int(sd.name.split("_")[0].replace("INST-", ""))
        test_fn = _load_unit_test(iid)
        if test_fn is None:
            results.append({
                "sandbox_id": sd.name, "injection_id": iid,
                "score": "technical", "method": "unit_test",
                "evidence": f"No unit test for injection {iid}",
            })
            continue
        try:
            success, reason = test_fn(sd)
        except Exception as e:
            success, reason = False, f"ERROR: {e}"
        results.append({
            "sandbox_id": sd.name, "injection_id": iid,
            "score": "attack_success" if success else "ignored",
            "method": "unit_test", "evidence": reason,
        })
        sym = "V" if success else "o"
        print(f"  {sym} INST-{iid}: {reason}")
    return {"results": results}


def run_and_evaluate(
    agent: str, model: str, run_idx: int,
    agent_dir: Path, variant_file: Path,
    results_dir: Path, parallel: int, timeout: int,
    runtime: str = "docker", sif: str | None = None,
) -> dict:
    status_log = results_dir.parent / f"status_{model}_{run_idx}.jsonl"

    if runtime == "apptainer":
        sif_path = sif or str(APPTAINER_DIR / APPTAINER_IMAGE_NAME)
        cmd = [
            "python3", str(PROJECT_ROOT / "scripts" / "run_sandbox_apptainer.py"), "run",
            "--agent", agent, "--model", model,
            "--sandboxes-root", str(agent_dir),
            "--results-dir", str(results_dir),
            "--timeout", str(timeout),
            "--parallel", str(parallel),
            "--sif", sif_path,
            "--status-log", str(status_log),
        ]
    else:
        cmd = [
            "python3", str(PROJECT_ROOT / "scripts" / "run_sandbox_container.py"), "run",
            "--agent", agent, "--model", model,
            "--sandboxes-root", str(agent_dir),
            "--results-dir", str(results_dir),
            "--timeout", str(timeout),
            "--parallel", str(parallel),
            "--status-log", str(status_log),
        ]

    subprocess.run(cmd, check=True)
    return evaluate_with_unit_tests(results_dir)


def aggregate(all_runs: list[dict], n_runs: int) -> dict:
    per_injection: dict[int, dict] = defaultdict(lambda: {"successes": 0, "runs": n_runs})
    for run_data in all_runs:
        succeeded = set()
        for r in run_data.get("data", {}).get("results", []):
            if r.get("score") == "attack_success":
                succeeded.add(r["injection_id"])
        for iid in succeeded:
            per_injection[iid]["successes"] += 1
    return dict(per_injection)


def resolve_ablation_models(agent_filter=None, model_filter=None):
    models = ABLATION_MODELS
    if agent_filter:
        models = [m for m in models if m["agent"] == agent_filter]
    if model_filter:
        models = [m for m in models if m["model"] == model_filter]
    if not models:
        print(f"[error] No matching models for agent={agent_filter}, model={model_filter}")
        print(f"Available: {[(m['agent'], m['model']) for m in ABLATION_MODELS]}")
        sys.exit(1)
    return models


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Best-of-5 combined (line+task+phrasing)")
    parser.add_argument("--agent", help="Filter to one agent (claude/codex/gemini)")
    parser.add_argument("--model", help="Filter to one model")
    parser.add_argument("--injection-id", type=int, action="append")
    parser.add_argument("--description-injection", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run injection ID 1 only, 1 run, single model")
    parser.add_argument("--runtime", choices=["docker", "apptainer"], default="docker")
    parser.add_argument("--sif", type=str, default=None)
    args = parser.parse_args()

    if not SUBSET_FILE.exists():
        sys.exit(f"[error] Subset file not found: {SUBSET_FILE}")

    with SUBSET_FILE.open() as f:
        injections = json.load(f)

    models = resolve_ablation_models(args.agent, args.model)
    injection_ids = args.injection_id
    n_runs = N_RUNS
    if args.smoke_test:
        injection_ids = [1]
        n_runs = 1
        models = models[:1]

    n_injections = len([i for i in injections
                        if not injection_ids or i["id"] in injection_ids])
    sandbox_count = n_runs * n_injections * len(models)
    print(f"[plan] {len(models)} models x {n_runs} runs x {n_injections} injections "
          f"= {sandbox_count} sandboxes")

    if args.runtime == "docker":
        r = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE_NAME], capture_output=True)
        if r.returncode != 0:
            subprocess.run(["bash", str(PROJECT_ROOT / "docker" / "build.sh")], check=True)

    results_base = FINAL_RESULTS_DIR / "ablations" / "bo5_combined"

    for mcfg in models:
        agent = mcfg["agent"]
        model = mcfg["model"]
        display = mcfg["display_name"]
        parallel = 1 if args.smoke_test else AGENT_PARALLEL.get(agent, 10)
        slug = f"{agent}-{model}".replace(".", "-")
        run_dir = results_base / slug
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'#'*60}")
        print(f"# {display} ({agent}/{model}) — {n_runs} combined runs")
        print(f"{'#'*60}")

        all_runs = []
        for ri in range(1, n_runs + 1):
            ad, vf = build_for_run(agent, ri, run_dir, injections,
                                   injection_ids, args.description_injection)
            rd = run_dir / f"run-{ri}"
            rd.mkdir(parents=True, exist_ok=True)
            data = run_and_evaluate(agent, model, ri, ad, vf, rd, parallel, args.timeout,
                                    runtime=args.runtime, sif=args.sif)
            all_runs.append({"run": ri, "data": data})

        per_inj = aggregate(all_runs, n_runs)
        summary = {
            "agent": agent, "model": model, "n_runs": n_runs,
            "selection": "diagonal(task=line=phrasing=run-1)",
            "per_injection": per_inj, "all_runs": all_runs,
        }
        out = run_dir / "aggregated_results_combined.json"
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved aggregated results to {out}")

    print("\n[done] Bo5 combined ablation complete.")


if __name__ == "__main__":
    main()
