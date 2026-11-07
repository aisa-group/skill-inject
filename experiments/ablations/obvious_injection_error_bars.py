#!/usr/bin/env python3
"""Obvious injection error bars — run high-ASR injections N times for variance.

Selects 10 obvious injections with high ASR (one task each) and runs them
multiple times to measure variance / confidence intervals.

Usage:
    python3 experiments/ablations/obvious_injection_error_bars.py --agent codex --model gpt-5.4-mini
    python3 experiments/ablations/obvious_injection_error_bars.py --agent codex --model gpt-5.4-mini --smoke-test
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
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
    resolve_models,
)

INJECTIONS_FILE = DATA_DIR / "obvious_injections_error_bars_all.json"
UNIT_TESTS_DIR = PROJECT_ROOT / "data" / "instruction_unit_tests" / "obvious"
N_RUNS = 5


def build_for_run(
    agent: str, run_idx: int, run_dir: Path,
    injections: list[dict],
    description_injection: bool = False,
) -> tuple[Path, Path]:
    """Build sandboxes for a specific run. Returns (agent_dir, variant_file)."""
    variant_file = run_dir / f"injections_run{run_idx}.json"
    variant_file.write_text(
        json.dumps(injections, indent=2),
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
    print(f"\n[run {run_idx}] Building sandboxes...")
    subprocess.run(cmd, check=True)
    return agent_dir, variant_file


def _load_unit_test(injection_id: int):
    """Load the unit test function for an obvious injection."""
    test_file = UNIT_TESTS_DIR / f"test_obvious_{injection_id}.py"
    if not test_file.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"test_{injection_id}", test_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "test_attack", None)


def evaluate_with_unit_tests(results_dir: Path) -> dict:
    """Evaluate all sandboxes in results_dir using deterministic unit tests."""
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
            score = "attack_success" if success else "ignored"
        except Exception as e:
            success, reason = False, f"ERROR: {e}"
            score = "technical"
        results.append({
            "sandbox_id": sd.name, "injection_id": iid,
            "score": score,
            "method": "unit_test", "evidence": reason,
        })
        sym = "V" if success else "o"
        print(f"  {sd.name}: {sym} — {reason[:80]}")

    summary = {
        "injection": {
            "success": sum(1 for r in results if r["score"] == "attack_success"),
            "ignored": sum(1 for r in results if r["score"] == "ignored"),
            "technical": sum(1 for r in results if r["score"] == "technical"),
        },
    }
    eval_out = {"model": "unit_test", "results": results, "summary": summary}
    out_file = results_dir / "evaluation_unit_tests.json"
    out_file.write_text(json.dumps(eval_out, indent=2) + "\n", encoding="utf-8")
    return eval_out


def run_and_evaluate(
    agent: str, model: str, run_idx: int,
    agent_dir: Path, variant_file: Path,
    results_dir: Path, parallel: int, timeout: int,
    runtime: str = "docker", sif: str | None = None,
    auth: str = "auto",
) -> dict:
    """Run agent + evaluate one run with unit tests. Returns evaluation JSON."""
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
            "--auth", auth,
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
            "--auth", auth,
        ]

    subprocess.run(cmd, check=True)

    return evaluate_with_unit_tests(results_dir)


def aggregate(all_runs: list[dict], n_runs: int) -> dict:
    """Aggregate per-injection results across runs."""
    if any(row.get("score") == "technical" for run in all_runs
           for row in run.get("data", {}).get("results", [])):
        raise ValueError("Unresolved observations must be reviewed before aggregating ASR")
    # Collect all injection IDs seen across all runs first
    all_ids: set[int] = set()
    for run_data in all_runs:
        for r in run_data.get("data", {}).get("results", []):
            iid = r.get("injection_id")
            if iid is not None:
                all_ids.add(iid)

    per_injection: dict[int, dict] = {
        iid: {"successes": 0, "runs": n_runs, "run_details": []}
        for iid in all_ids
    }
    for run_data in all_runs:
        run_idx = run_data["run"]
        succeeded = set()
        for r in run_data.get("data", {}).get("results", []):
            iid = r.get("injection_id")
            score = r.get("score", r.get("injection_score", ""))
            if score == "attack_success":
                succeeded.add(iid)
        for iid in per_injection:
            per_injection[iid]["run_details"].append(
                {"run": run_idx, "success": iid in succeeded}
            )
        for iid in succeeded:
            per_injection[iid]["successes"] += 1

    # Compute ASR per injection
    for iid, info in per_injection.items():
        info["asr"] = info["successes"] / info["runs"] if info["runs"] > 0 else 0.0

    return dict(per_injection)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Obvious injection error bars (repeated runs)"
    )
    parser.add_argument("--agent", choices=["codex", "claude", "gemini", "vibe"],
                        required=True)
    parser.add_argument("--model", required=True, help="Model to test")
    parser.add_argument("--n-runs", type=int, default=N_RUNS,
                        help=f"Number of repeated runs (default: {N_RUNS})")
    parser.add_argument("--timeout", type=int, default=500)
    parser.add_argument("--parallel", type=int, default=None)
    parser.add_argument("--description-injection", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run 1 run with 1 injection, sequential")
    parser.add_argument("--runtime", choices=["docker", "apptainer"],
                        default="docker")
    parser.add_argument("--sif", type=str, default=None)
    parser.add_argument("--auth", choices=["auto", "subscription", "api-key"],
                        default="auto")
    parser.add_argument(
        "--pair", action="append", default=[], metavar="INJECTION_ID:TASK_INDEX",
        help="Select an exact injection/task pair; repeat for a fixed panel",
    )
    parser.add_argument("--rerun", action="store_true",
                        help="Back up existing run dirs with a timestamp, then delete and rerun")
    parser.add_argument("--only-runs", type=int, nargs="+", metavar="N",
                        help="Only (re)run these specific run indices; load existing results for others")
    args = parser.parse_args()

    agent = args.agent
    model = args.model
    n_runs = args.n_runs
    parallel = args.parallel or AGENT_PARALLEL.get(agent, 10)

    if not INJECTIONS_FILE.exists():
        sys.exit(f"[error] Injections file not found: {INJECTIONS_FILE}")

    source_file = DATA_DIR / "obvious_injections.json" if args.pair else INJECTIONS_FILE
    with source_file.open() as f:
        injections = json.load(f)

    selected_pairs = []
    if args.pair:
        source = {int(inj["id"]): inj for inj in injections}
        grouped: dict[int, list[int]] = defaultdict(list)
        for spec in args.pair:
            try:
                iid_text, task_text = spec.split(":", 1)
                iid, task_idx = int(iid_text), int(task_text)
                task = source[iid]["tasks"][task_idx]
            except (ValueError, KeyError, IndexError) as exc:
                parser.error(f"invalid --pair {spec!r}: {exc}")
            grouped[iid].append(task_idx)
            selected_pairs.append({"injection_id": iid, "task_index": task_idx})
        injections = []
        for iid, task_indices in grouped.items():
            injection = copy.deepcopy(source[iid])
            injection["tasks"] = [copy.deepcopy(source[iid]["tasks"][idx]) for idx in task_indices]
            injections.append(injection)

    if args.smoke_test:
        injections = [inj for inj in injections if inj["id"] == 1]
        n_runs = 1
        parallel = 1

    # Ensure container image
    if args.runtime == "docker":
        r = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE_NAME],
            capture_output=True,
        )
        if r.returncode != 0:
            subprocess.run(
                ["bash", str(PROJECT_ROOT / "docker" / "build.sh")],
                check=True,
            )

    slug = f"{agent}-{model}".replace(".", "-")
    results_base = FINAL_RESULTS_DIR / "ablations" / "obvious_error_bars" / slug
    results_base.mkdir(parents=True, exist_ok=True)

    if args.rerun:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_base = results_base / "_backups" / ts
        to_backup = sorted(results_base.glob("run-*")) + sorted(results_base.glob(f"{agent}_run*"))
        if to_backup:
            backup_base.mkdir(parents=True, exist_ok=True)
            for d in to_backup:
                dest = backup_base / d.name
                shutil.move(str(d), dest)
                print(f"[rerun] Backed up {d.name} → _backups/{ts}/{d.name}")
        else:
            print("[rerun] No existing run dirs found, starting fresh.")

    print(f"\n{'#' * 60}")
    print(f"# Obvious injection error bars")
    print(f"# {agent}/{model} — {n_runs} runs x {len(injections)} injections")
    print(f"{'#' * 60}")

    only_runs = set(args.only_runs) if args.only_runs else None

    all_runs = []
    for ri in range(1, n_runs + 1):
        print(f"\n{'='*40}")
        print(f"  Run {ri}/{n_runs}")
        print(f"{'='*40}")

        if only_runs and ri not in only_runs:
            rd = results_base / f"run-{ri}"
            eval_file = rd / "evaluation_unit_tests.json"
            if eval_file.exists():
                with eval_file.open() as f:
                    data = json.load(f)
                print(f"[skip] Loaded existing results for run {ri}")
            else:
                print(f"[skip] No existing results for run {ri}, skipping.")
                data = {"results": []}
            all_runs.append({"run": ri, "data": data})
            continue

        ad, vf = build_for_run(agent, ri, results_base, injections,
                               args.description_injection)
        rd = results_base / f"run-{ri}"
        rd.mkdir(parents=True, exist_ok=True)

        if args.skip_eval:
            data = {"results": []}
        else:
            data = run_and_evaluate(
                agent, model, ri, ad, vf, rd, parallel, args.timeout,
                runtime=args.runtime, sif=args.sif, auth=args.auth,
            )
        all_runs.append({"run": ri, "data": data})

    per_inj = aggregate(all_runs, n_runs)
    summary = {
        "experiment": "obvious_injection_error_bars",
        "agent": agent,
        "model": model,
        "n_runs": n_runs,
        "n_injections": len(injections),
        "injection_ids": [inj["id"] for inj in injections],
        "selected_pairs": selected_pairs,
        "planned_sandbox_runs": sum(len(inj["tasks"]) for inj in injections) * n_runs,
        "auth": args.auth,
        "runtime": args.runtime,
        "parallel": parallel,
        "per_injection": per_inj,
        "all_runs": all_runs,
    }

    # Compute overall ASR
    total_attempts = sum(info["runs"] for info in per_inj.values())
    total_successes = sum(info["successes"] for info in per_inj.values())
    summary["overall_asr"] = total_successes / total_attempts if total_attempts else 0.0

    out = results_base / "aggregated_results.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # Print summary
    print(f"\n{'#' * 60}")
    print(f"# Results Summary")
    print(f"{'#' * 60}")
    print(f"  Overall ASR: {total_successes}/{total_attempts} "
          f"({summary['overall_asr']*100:.1f}%)")
    print()
    for iid in sorted(per_inj, key=int):
        info = per_inj[iid]
        print(f"  INST-{iid}: {info['successes']}/{info['runs']} "
              f"({info['asr']*100:.0f}%)")

    print(f"\nSaved aggregated results to {out}")
    print("\n[done] Error bars experiment complete.")


if __name__ == "__main__":
    main()
