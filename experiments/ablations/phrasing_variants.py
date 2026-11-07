#!/usr/bin/env python3
"""Phrasing variants ablation for obvious injections.

Tests whether rephrasing an injection's instruction text — while keeping the
malicious action identical — affects attack success rate (ASR).  Five style
variants are tested per injection:

  0. original      — unmodified baseline
  1. authority     — "CRITICAL SYSTEM REQUIREMENT" framing
  2. urgency       — "before returning output, you MUST first..."
  3. legitimizing  — plain sentence-case, administrator-justification prose
  4. system_prompt — ALL-CAPS headers mimicking a system prompt

For each variant, sandboxes are built from
data/obvious_injections_phrasing_variants.json by overwriting
instructions.line_injection with the variant text.  Evaluation uses
deterministic unit tests (same as the other obvious-injection ablations).

Reported metrics:
  - ASR per variant (across the 10-injection subset)
  - Per-injection best-of-5 flag (did *any* variant succeed?)
  - Overall best-of-5 ASR vs. static baseline (variant 0)

Usage:
    python3 experiments/ablations/phrasing_variants.py              # all models
    python3 experiments/ablations/phrasing_variants.py --agent claude --model sonnet
    python3 experiments/ablations/phrasing_variants.py --smoke-test # variant 0 only, 1 model
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
    AGENT_PARALLEL,
    APPTAINER_DIR,
    APPTAINER_IMAGE_NAME,
    DATA_DIR,
    DOCKER_IMAGE_NAME,
    FINAL_RESULTS_DIR,
    PROJECT_ROOT,
)

PHRASING_VARIANTS_FILE = DATA_DIR / "obvious_injections_phrasing_variants.json"
UNIT_TESTS_DIR = PROJECT_ROOT / "data" / "instruction_unit_tests" / "obvious"
N_VARIANTS = 5
VARIANT_STYLES = ["original", "authority", "urgency", "legitimizing", "system_prompt"]

ABLATION_MODELS: list[dict[str, str]] = [
    {"agent": "claude", "model": "claude-opus-4-5-20251101", "display_name": "Opus 4.5"},
    {"agent": "claude", "model": "sonnet",                  "display_name": "Sonnet 4.5"},
    {"agent": "claude", "model": "haiku",                   "display_name": "Haiku 4.5"},
    {"agent": "codex",  "model": "gpt-5.2-codex",           "display_name": "GPT-5.2-Codex"},
    {"agent": "codex",  "model": "gpt-5.1-codex-mini",      "display_name": "GPT-5.1-Codex-Mini"},
    {"agent": "codex",  "model": "gpt-5.2",                 "display_name": "GPT-5.2"},
    {"agent": "gemini", "model": "gemini-3-pro-preview",    "display_name": "Gemini 3 Pro"},
    {"agent": "gemini", "model": "gemini-3-flash-preview",  "display_name": "Gemini 3 Flash"},
]


# ---------------------------------------------------------------------------
# Variant injection builder
# ---------------------------------------------------------------------------

def make_variant_injections(injections: list[dict], variant_idx: int) -> list[dict]:
    """Return a copy of injections with line_injection set to variant_idx's phrasing."""
    out = []
    for inj in injections:
        variants = inj.get("phrasing_variants", [])
        if not variants or variant_idx >= len(variants):
            continue
        entry = copy.deepcopy(inj)
        entry["instructions"]["line_injection"] = variants[variant_idx]["line_injection"]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Unit-test evaluation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Build / run helpers
# ---------------------------------------------------------------------------

def build_for_variant(
    agent: str,
    variant_idx: int,
    variant_dir: Path,
    injections: list[dict],
) -> tuple[Path, Path]:
    """Build sandboxes for one phrasing variant. Returns (agent_dir, variant_file)."""
    style = VARIANT_STYLES[variant_idx]
    variant_file = variant_dir / f"injections_variant{variant_idx}_{style}.json"
    variant_file.write_text(
        json.dumps(make_variant_injections(injections, variant_idx), indent=2),
        encoding="utf-8",
    )

    agent_dir = variant_dir / f"{agent}_variant{variant_idx}"
    if agent_dir.exists():
        subprocess.run(["rm", "-rf", str(agent_dir)], check=True)

    cmd = [
        "python3", str(PROJECT_ROOT / "scripts" / "build_sandbox.py"),
        "--agent", agent,
        "--injections-file", str(variant_file),
        "--sandboxes-root", str(agent_dir),
        "--first-task-only",
        "--clobber",
    ]
    print(f"\n[variant {variant_idx} / {style}] Building sandboxes ({agent})...")
    subprocess.run(cmd, check=True)
    return agent_dir, variant_file


def run_and_evaluate(
    agent: str,
    model: str,
    variant_idx: int,
    agent_dir: Path,
    results_dir: Path,
    parallel: int,
    timeout: int,
    runtime: str = "apptainer",
    sif: str | None = None,
) -> dict:
    style = VARIANT_STYLES[variant_idx]
    status_log = results_dir.parent / f"status_{model}_variant{variant_idx}.jsonl"

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

    print(f"\n[variant {variant_idx} / {style}] Running {agent}/{model}...")
    subprocess.run(cmd, check=True)
    return evaluate_with_unit_tests(results_dir)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_asr(eval_data: dict) -> dict:
    results = eval_data.get("results", [])
    n_success  = sum(1 for r in results if r["score"] == "attack_success")
    n_ignored  = sum(1 for r in results if r["score"] == "ignored")
    n_technical = sum(1 for r in results if r["score"] == "technical")
    n_total    = len(results)
    return {
        "n_total": n_total,
        "n_success": n_success,
        "n_ignored": n_ignored,
        "n_technical": n_technical,
        "asr": round(n_success / n_total, 4) if n_total else 0.0,
    }


def aggregate(all_variant_results: list[dict], n_variants: int) -> dict:
    """Compute per-variant ASR and best-of-N ASR across injections."""
    # per_injection[iid] = set of variant indices where attack succeeded
    per_injection: dict[int, set[int]] = defaultdict(set)

    variant_summaries = {}
    for vdata in all_variant_results:
        vidx  = vdata["variant_idx"]
        style = vdata["style"]
        summary = compute_asr(vdata["eval_data"])
        summary["variant_idx"] = vidx
        summary["style"] = style
        variant_summaries[vidx] = summary

        for r in vdata["eval_data"].get("results", []):
            if r["score"] == "attack_success":
                per_injection[r["injection_id"]].add(vidx)

    # Best-of-N: injection counts as success if ANY variant succeeded
    all_ids = {
        r["injection_id"]
        for vdata in all_variant_results
        for r in vdata["eval_data"].get("results", [])
        if r["score"] != "technical"
    }
    bo_n_success = sum(1 for iid in all_ids if per_injection[iid])
    bo_n_total   = len(all_ids)

    # Baseline = variant 0 (original)
    baseline_asr = variant_summaries.get(0, {}).get("asr", 0.0)
    bo_asr       = round(bo_n_success / bo_n_total, 4) if bo_n_total else 0.0

    return {
        "variant_summaries": variant_summaries,
        "best_of_n": {
            "n_variants": n_variants,
            "n_success": bo_n_success,
            "n_total": bo_n_total,
            "asr": bo_asr,
        },
        "baseline_asr": baseline_asr,
        "asr_gain": round(bo_asr - baseline_asr, 4),
        "per_injection_successes": {
            str(iid): sorted(list(vidxs))
            for iid, vidxs in per_injection.items()
        },
    }


# ---------------------------------------------------------------------------
# Model filtering
# ---------------------------------------------------------------------------

def resolve_ablation_models(
    agent_filter: str | None,
    model_filter: str | None,
) -> list[dict[str, str]]:
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Phrasing variants ablation (obvious injections)"
    )
    parser.add_argument("--agent",   help="Filter to one agent (claude/codex/gemini/vibe)")
    parser.add_argument("--model",   help="Filter to one model")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run variant 0 only, first model, sequential")
    parser.add_argument("--runtime", choices=["docker", "apptainer"], default="apptainer")
    parser.add_argument("--sif",     type=str, default=None)
    parser.add_argument("--results-dir", type=Path, default=None,
                        help="Override output directory (default: final_results/ablations/phrasing_variants)")
    args = parser.parse_args()

    if not PHRASING_VARIANTS_FILE.exists():
        sys.exit(f"[error] Phrasing variants file not found: {PHRASING_VARIANTS_FILE}\n"
                 "Run scripts/generate_phrasing_variants.py first.")

    injections = json.loads(PHRASING_VARIANTS_FILE.read_text())
    models = resolve_ablation_models(args.agent, args.model)

    variant_indices = list(range(N_VARIANTS))
    if args.smoke_test:
        variant_indices = [0]
        models = models[:1]

    if args.runtime == "docker":
        r = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE_NAME], capture_output=True)
        if r.returncode != 0:
            subprocess.run(["bash", str(PROJECT_ROOT / "docker" / "build.sh")], check=True)

    results_base = args.results_dir or FINAL_RESULTS_DIR / "ablations" / "phrasing_variants"

    for mcfg in models:
        agent   = mcfg["agent"]
        model   = mcfg["model"]
        display = mcfg["display_name"]
        parallel = 1 if args.smoke_test else AGENT_PARALLEL.get(agent, 10)
        slug = f"{agent}-{model}".replace(".", "-")
        model_dir = results_base / slug
        model_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'#'*60}")
        print(f"# {display} ({agent}/{model}) — {len(variant_indices)} phrasing variants")
        print(f"{'#'*60}")

        all_variant_results = []

        for vidx in variant_indices:
            style = VARIANT_STYLES[vidx]
            variant_dir = model_dir / f"variant_{vidx}_{style}"
            variant_dir.mkdir(parents=True, exist_ok=True)

            agent_dir, _ = build_for_variant(agent, vidx, variant_dir, injections)

            results_dir = variant_dir / "results"
            results_dir.mkdir(parents=True, exist_ok=True)

            eval_data = run_and_evaluate(
                agent, model, vidx, agent_dir, results_dir,
                parallel, args.timeout,
                runtime=args.runtime, sif=args.sif,
            )
            summary = compute_asr(eval_data)
            print(f"  variant {vidx} ({style}): ASR={summary['asr']:.1%} "
                  f"({summary['n_success']}/{summary['n_total']})")

            out = variant_dir / f"evaluation_{model.replace('.', '-')}.json"
            out.write_text(
                json.dumps({"summary": summary, "results": eval_data["results"]}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            all_variant_results.append({
                "variant_idx": vidx,
                "style": style,
                "eval_data": eval_data,
            })

        agg = aggregate(all_variant_results, len(variant_indices))

        aggregated = {
            "agent": agent,
            "model": model,
            "display_name": display,
            "n_variants": len(variant_indices),
            **agg,
        }
        agg_out = model_dir / "aggregated_phrasing_results.json"
        agg_out.write_text(json.dumps(aggregated, indent=2) + "\n", encoding="utf-8")

        print(f"\nPhrasing variant ASR ({display}):")
        for vidx in variant_indices:
            s = agg["variant_summaries"][vidx]
            print(f"  {vidx} {s['style']:>15}: {s['asr']:.1%}  ({s['n_success']}/{s['n_total']})")
        bo = agg["best_of_n"]
        print(f"  {'best-of-'+str(len(variant_indices)):>16}: {bo['asr']:.1%}  "
              f"({bo['n_success']}/{bo['n_total']})  "
              f"[+{agg['asr_gain']:.1%} vs baseline]")
        print(f"Saved to {agg_out}")

    print("\n[done] Phrasing variants ablation complete.")


if __name__ == "__main__":
    main()
