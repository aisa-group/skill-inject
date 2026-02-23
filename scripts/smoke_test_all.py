#!/usr/bin/env python3
"""End-to-end smoke test: run every experiment with every model on one sandbox.

Builds the Docker image, then for each (agent, model, experiment) combination
executes a minimal run (single injection / single task) and verifies that
results are produced.

Usage:
    # Test everything (all agents, all models, all experiments)
    python scripts/smoke_test_all.py

    # Test a single agent
    python scripts/smoke_test_all.py --agent claude

    # Test a single agent/model
    python scripts/smoke_test_all.py --agent claude --model sonnet

    # Skip evaluation phase (only test build + run)
    python scripts/smoke_test_all.py --skip-eval

    # Dry run (print what would be executed)
    python scripts/smoke_test_all.py --dry-run

    # Custom timeout per sandbox (default: 180s)
    python scripts/smoke_test_all.py --timeout 120
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROJECT_ROOT, AGENT_MODELS, DOCKER_IMAGE_NAME, resolve_models


# ---------------------------------------------------------------------------
# Experiment definitions
# ---------------------------------------------------------------------------

EXPERIMENTS: list[dict] = [
    {
        "name": "contextual",
        "script": "experiments/contextual.py",
        "args": ["--smoke-test"],
        "skip_eval_flag": "--skip-eval",
        "supports_force": True,
    },
    {
        "name": "obvious",
        "script": "experiments/obvious.py",
        "args": ["--smoke-test"],
        "skip_eval_flag": "--skip-eval",
        "supports_force": True,
    },
    {
        "name": "utility_baseline",
        "script": "experiments/utility_baseline.py",
        "args": ["--task-id", "1", "--condition", "no_policy"],
        "skip_eval_flag": "--skip-eval",
        "supports_force": True,
    },
    {
        "name": "ablation/script_vs_direct",
        "script": "experiments/ablations/script_vs_direct.py",
        "args": ["--smoke-test"],
        "skip_eval_flag": "--skip-eval",
        "supports_force": False,
    },
    {
        "name": "ablation/bo5_byline",
        "script": "experiments/ablations/bo5_byline.py",
        "args": ["--smoke-test"],
        "skip_eval_flag": "--skip-eval",
        "supports_force": False,
    },
    {
        "name": "ablation/bo4_bytask",
        "script": "experiments/ablations/bo4_bytask.py",
        "args": ["--smoke-test"],
        "skip_eval_flag": "--skip-eval",
        "supports_force": False,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_docker_image() -> bool:
    """Check Docker image exists, build if missing. Returns True on success."""
    r = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE_NAME],
        capture_output=True,
    )
    if r.returncode == 0:
        return True

    print("[build] Docker image not found, building...")
    r = subprocess.run(
        ["bash", str(PROJECT_ROOT / "docker" / "build.sh")],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[error] Docker build failed:\n{r.stderr[-500:]}")
        return False
    print("[build] Docker image ready")
    return True


def run_experiment(
    experiment: dict,
    agent: str,
    model: str,
    timeout: int,
    skip_eval: bool,
    dry_run: bool,
) -> dict:
    """Run a single experiment for one agent/model. Returns result dict."""
    name = experiment["name"]
    script = PROJECT_ROOT / experiment["script"]

    cmd = [
        sys.executable, str(script),
        "--agent", agent,
        "--model", model,
        "--timeout", str(timeout),
    ]
    if experiment.get("supports_force", False):
        cmd.append("--force")
    cmd += experiment["args"]

    if skip_eval and experiment.get("skip_eval_flag"):
        cmd.append(experiment["skip_eval_flag"])

    result = {
        "experiment": name,
        "agent": agent,
        "model": model,
        "status": "skipped",
        "duration": 0.0,
        "error": None,
    }

    label = f"{name} / {agent} / {model}"

    if dry_run:
        print(f"  [dry-run] {label}")
        print(f"            {' '.join(cmd)}")
        result["status"] = "dry_run"
        return result

    print(f"  [run] {label} ...", end=" ", flush=True)
    t0 = time.time()

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 120,  # extra buffer beyond sandbox timeout
        )
        result["duration"] = time.time() - t0

        if r.returncode == 0:
            result["status"] = "pass"
            print(f"PASS ({result['duration']:.0f}s)")
        else:
            result["status"] = "fail"
            # Extract last meaningful error lines
            stderr_lines = [
                l for l in r.stderr.strip().splitlines()
                if l.strip() and not l.startswith("Traceback")
            ]
            error_msg = stderr_lines[-1] if stderr_lines else f"exit code {r.returncode}"
            result["error"] = error_msg
            print(f"FAIL ({result['duration']:.0f}s)")
            print(f"         {error_msg}")

    except subprocess.TimeoutExpired:
        result["duration"] = time.time() - t0
        result["status"] = "timeout"
        result["error"] = f"Timed out after {timeout + 120}s"
        print(f"TIMEOUT ({result['duration']:.0f}s)")

    except Exception as exc:
        result["duration"] = time.time() - t0
        result["status"] = "error"
        result["error"] = str(exc)
        print(f"ERROR: {exc}")

    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]) -> int:
    """Print a summary table. Returns exit code (0 = all pass)."""
    if not results:
        print("\nNo tests were run.")
        return 1

    # Collect all experiments, agents, models
    experiments = list(dict.fromkeys(r["experiment"] for r in results))
    agents_models = list(dict.fromkeys((r["agent"], r["model"]) for r in results))

    # Build lookup
    lookup = {}
    for r in results:
        lookup[(r["experiment"], r["agent"], r["model"])] = r

    # Print table
    print(f"\n{'=' * 80}")
    print("  SMOKE TEST SUMMARY")
    print(f"{'=' * 80}\n")

    pass_count = sum(1 for r in results if r["status"] == "pass")
    fail_count = sum(1 for r in results if r["status"] == "fail")
    timeout_count = sum(1 for r in results if r["status"] == "timeout")
    error_count = sum(1 for r in results if r["status"] == "error")
    total = len(results)

    # Per agent/model summary
    for agent, model in agents_models:
        agent_results = [r for r in results if r["agent"] == agent and r["model"] == model]
        passed = sum(1 for r in agent_results if r["status"] in ("pass", "dry_run"))
        total_am = len(agent_results)
        status = "PASS" if passed == total_am else "FAIL"
        print(f"  {agent}/{model}: {status} ({passed}/{total_am})")

        for r in agent_results:
            sym = {"pass": "V", "fail": "X", "timeout": "T", "error": "E", "dry_run": "-"}.get(
                r["status"], "?"
            )
            line = f"    [{sym}] {r['experiment']}"
            if r["duration"]:
                line += f" ({r['duration']:.0f}s)"
            if r["error"]:
                line += f" -- {r['error']}"
            print(line)
        print()

    # Totals
    print(f"{'=' * 80}")
    print(f"  Total: {total}  Pass: {pass_count}  Fail: {fail_count}  "
          f"Timeout: {timeout_count}  Error: {error_count}")
    print(f"{'=' * 80}")

    if fail_count + timeout_count + error_count == 0:
        print("\n  All smoke tests passed.\n")
        return 0
    else:
        print(f"\n  {fail_count + timeout_count + error_count} test(s) failed.\n")
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test for all experiments and models"
    )
    parser.add_argument("--agent", choices=list(AGENT_MODELS.keys()),
                        help="Test only this agent (default: all)")
    parser.add_argument("--model", help="Test only this model (default: all per agent)")
    parser.add_argument("--experiment", help="Test only experiments matching this name")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Timeout per sandbox in seconds (default: 180)")
    parser.add_argument("--skip-eval", action="store_true",
                        help="Skip evaluation phase (only test build + run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without executing")
    args = parser.parse_args()

    # Resolve which agents and models to test
    if args.agent:
        agents = [args.agent]
    else:
        agents = list(AGENT_MODELS.keys())

    agent_models: list[tuple[str, str]] = []
    for agent in agents:
        models = resolve_models(agent, args.model)
        for m in models:
            agent_models.append((agent, m["model"]))

    if not agent_models:
        print("[error] No agent/model combinations to test.")
        sys.exit(1)

    # Filter experiments
    experiments = EXPERIMENTS
    if args.experiment:
        experiments = [e for e in experiments if args.experiment in e["name"]]
        if not experiments:
            print(f"[error] No experiments matching '{args.experiment}'")
            sys.exit(1)

    total_runs = len(agent_models) * len(experiments)
    print(f"\nSmoke test: {len(agent_models)} agent/model combo(s) x "
          f"{len(experiments)} experiment(s) = {total_runs} run(s)\n")

    for agent, model in agent_models:
        print(f"  - {agent}/{model}")
    print()
    for e in experiments:
        print(f"  - {e['name']}")
    print()

    # Ensure Docker image
    if not args.dry_run:
        if not ensure_docker_image():
            print("[error] Docker image build failed. Aborting.")
            sys.exit(1)

    # Run all combinations
    results: list[dict] = []
    t0 = time.time()

    for agent, model in agent_models:
        print(f"\n--- {agent} / {model} ---")
        for experiment in experiments:
            r = run_experiment(
                experiment=experiment,
                agent=agent,
                model=model,
                timeout=args.timeout,
                skip_eval=args.skip_eval,
                dry_run=args.dry_run,
            )
            results.append(r)

    total_duration = time.time() - t0

    # Summary
    exit_code = print_summary(results)
    print(f"  Total time: {total_duration:.0f}s\n")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
