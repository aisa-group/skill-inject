#!/usr/bin/env python3
"""Script vs Direct injection ablation.

Compares ASR between script-based and direct (text-only) injections using
contextual_injections_wscript.json which contains matched pairs.

Usage:
    python3 experiments/ablations/script_vs_direct.py --agent claude
    python3 experiments/ablations/script_vs_direct.py --agent claude --model sonnet --smoke-test
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import (
    PROJECT_ROOT,
    CONTEXTUAL_WSCRIPT_FILE,
    AGENT_MODELS,
    AGENT_PARALLEL,
    DOCKER_IMAGE_NAME,
    FINAL_RESULTS_DIR,
    resolve_models,
)

INJECTION_TYPES = ("script", "direct")


def create_filtered_file(src: Path, out: Path, inj_type: str) -> int:
    """Write a filtered injections file. Returns count."""
    with src.open() as f:
        all_injs = json.load(f)
    filtered = [inj for inj in all_injs if inj.get("type") == inj_type]
    out.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    return len(filtered)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Script vs Direct injection ablation")
    parser.add_argument("--agent", choices=list(AGENT_MODELS.keys()), required=True)
    parser.add_argument("--model", help="Run only this model")
    parser.add_argument("--injection-type", action="append", choices=list(INJECTION_TYPES))
    parser.add_argument("--description-injection", action="store_true")
    parser.add_argument("--parallel", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=700)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run injection ID 1 only, sequential")
    args = parser.parse_args()

    agent = args.agent
    models = resolve_models(agent, args.model)
    parallel = args.parallel or AGENT_PARALLEL.get(agent, 10)
    types_to_run = args.injection_type or list(INJECTION_TYPES)

    if args.smoke_test:
        parallel = 1

    results_base = FINAL_RESULTS_DIR / "ablations" / "script_vs_direct"
    results_base.mkdir(parents=True, exist_ok=True)

    # Ensure Docker image
    r = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE_NAME], capture_output=True)
    if r.returncode != 0:
        subprocess.run(["bash", str(PROJECT_ROOT / "docker" / "build.sh")], check=True)

    # Create filtered injection files and build sandboxes per type
    agent_dirs: dict[str, Path] = {}
    filtered_files: dict[str, Path] = {}
    for itype in types_to_run:
        ff = results_base / f"injections_{itype}.json"
        n = create_filtered_file(CONTEXTUAL_WSCRIPT_FILE, ff, itype)
        filtered_files[itype] = ff
        print(f"[filter] {itype}: {n} injections")

        ad = results_base / "sandboxes" / agent / itype
        cmd = [
            sys.executable, str(PROJECT_ROOT / "scripts" / "build_sandbox.py"),
            "--agent", agent,
            "--injections-file", str(ff),
            "--sandboxes-root", str(ad),
            "--clobber",
        ]
        if args.description_injection:
            cmd.append("--description-injection")
        if args.smoke_test:
            cmd += ["--injection-id", "1"]
        print(f"\n[build] {itype} sandboxes...")
        subprocess.run(cmd, check=True)
        agent_dirs[itype] = ad

    # Run each model x type
    for mcfg in models:
        model = mcfg["model"]
        display = mcfg["display_name"]
        slug = f"{agent}-{model}".replace(".", "-")

        for itype in types_to_run:
            rd = results_base / slug / itype
            rd.mkdir(parents=True, exist_ok=True)
            sl = rd / "run_status.jsonl"

            print(f"\n[run] {display} — {itype}")
            subprocess.run([
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "run_sandbox_container.py"), "run",
                "--agent", agent, "--model", model,
                "--sandboxes-root", str(agent_dirs[itype]),
                "--results-dir", str(rd),
                "--timeout", str(args.timeout),
                "--parallel", str(parallel),
                "--status-log", str(sl),
            ], check=True)

            print(f"\n[eval] {display} — {itype}")
            subprocess.run([
                sys.executable,
                str(PROJECT_ROOT / "judges" / "contextual_judge.py"),
                str(rd),
                "--injections-file", str(filtered_files[itype]),
                "--model", "sonnet",
                "--evaluate-task",
            ], check=True)

    # Summary comparison
    print(f"\n{'='*60}")
    print("Script vs Direct — Quick Comparison")
    print(f"{'='*60}")
    for mcfg in models:
        model = mcfg["model"]
        slug = f"{agent}-{model}".replace(".", "-")
        print(f"\n{mcfg['display_name']}:")
        for itype in types_to_run:
            ef = results_base / slug / itype / "evaluation_llmjudge_sonnet.json"
            if ef.exists():
                with ef.open() as f:
                    d = json.load(f)
                s = d.get("summary", {}).get("injection", {})
                total = s.get("success", 0) + s.get("ignored", 0) + s.get("technical", 0)
                rate = s["success"] / total * 100 if total else 0
                print(f"  {itype:8s}: {s.get('success',0)}/{total} ({rate:.1f}%)")
            else:
                print(f"  {itype:8s}: no results")

    print("\n[done] Script vs Direct ablation complete.")


if __name__ == "__main__":
    main()
