#!/usr/bin/env python3
"""Compare deterministic unit test results against LLM judge results.

Usage:
    python3 scripts/compare_judges.py [--agent AGENT] [--model MODEL]

Runs the new deterministic unit tests against all obvious injection sandboxes
and compares verdicts with the existing LLM judge evaluation JSONs.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data" / "instruction_unit_tests"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OBVIOUS_RESULTS = PROJECT_ROOT / "final_results" / "obvious"
TESTS_DIR = PROJECT_ROOT / "data" / "instruction_unit_tests" / "obvious"


def load_test(injection_id: int):
    """Load the unit test module for an obvious injection."""
    test_file = TESTS_DIR / f"test_obvious_{injection_id}.py"
    if not test_file.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"test_{injection_id}", test_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "test_attack", None)


def load_llm_results(results_dir: Path) -> dict[str, str]:
    """Load the LLM judge evaluation and return {sandbox_id: score}."""
    for f in sorted(results_dir.glob("evaluation_llmjudge_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return {r["sandbox_id"]: r["score"] for r in data["results"]}
        except Exception:
            continue
    return {}


def run_comparison(agent_model_dir: Path) -> dict:
    """Run unit tests and compare with LLM judge for one agent-model dir."""
    policy_dir = agent_model_dir / "normal"
    if not policy_dir.exists():
        return {}

    llm_results = load_llm_results(policy_dir)
    if not llm_results:
        return {}

    sandboxes = sorted(
        d for d in policy_dir.iterdir()
        if d.is_dir() and d.name.startswith("INST-")
    )

    stats = {
        "agree_success": 0,  # both say attack_success
        "agree_ignored": 0,  # both say ignored/failed
        "unit_yes_llm_no": 0,  # unit test says success, LLM says no (FP?)
        "unit_no_llm_yes": 0,  # unit test says no, LLM says yes (FN?)
        "unit_no_test": 0,  # no unit test available
        "llm_technical": 0,  # LLM said technical failure
        "total": 0,
        "disagreements": [],
    }

    for sandbox in sandboxes:
        parts = sandbox.name.split("_")
        iid = int(parts[0].replace("INST-", ""))

        test_fn = load_test(iid)
        llm_score = llm_results.get(sandbox.name, None)

        if llm_score is None:
            continue

        stats["total"] += 1

        if llm_score == "technical":
            stats["llm_technical"] += 1
            continue

        if test_fn is None:
            stats["unit_no_test"] += 1
            continue

        try:
            unit_success, unit_reason = test_fn(sandbox)
        except Exception as e:
            unit_success = False
            unit_reason = f"ERROR: {e}"

        llm_success = llm_score == "attack_success"

        if unit_success and llm_success:
            stats["agree_success"] += 1
        elif not unit_success and not llm_success:
            stats["agree_ignored"] += 1
        elif unit_success and not llm_success:
            stats["unit_yes_llm_no"] += 1
            stats["disagreements"].append({
                "sandbox": sandbox.name,
                "injection_id": iid,
                "type": "UNIT=success LLM=ignored",
                "unit_reason": unit_reason[:120],
            })
        else:
            stats["unit_no_llm_yes"] += 1
            stats["disagreements"].append({
                "sandbox": sandbox.name,
                "injection_id": iid,
                "type": "UNIT=ignored LLM=success",
                "unit_reason": unit_reason[:120],
            })

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", help="Filter by agent prefix (e.g., 'claude')")
    parser.add_argument("--model", help="Filter by model (e.g., 'claude-sonnet')")
    parser.add_argument("--show-disagreements", action="store_true", default=True)
    args = parser.parse_args()

    if not OBVIOUS_RESULTS.exists():
        sys.exit(f"No results dir: {OBVIOUS_RESULTS}")

    agent_dirs = sorted(d for d in OBVIOUS_RESULTS.iterdir() if d.is_dir())
    if args.agent:
        agent_dirs = [d for d in agent_dirs if d.name.startswith(args.agent)]
    if args.model:
        agent_dirs = [d for d in agent_dirs if args.model in d.name]

    grand_totals = defaultdict(int)
    all_disagreements = []

    for agent_dir in agent_dirs:
        stats = run_comparison(agent_dir)
        if not stats or stats.get("total", 0) == 0:
            continue

        tested = stats["total"] - stats["llm_technical"] - stats["unit_no_test"]
        agree = stats["agree_success"] + stats["agree_ignored"]
        agreement_pct = (agree / tested * 100) if tested > 0 else 0

        print(f"\n{'='*60}")
        print(f"  {agent_dir.name}")
        print(f"{'='*60}")
        print(f"  Total sandboxes:    {stats['total']}")
        print(f"  LLM technical:      {stats['llm_technical']}")
        print(f"  No unit test:       {stats['unit_no_test']}")
        print(f"  Testable:           {tested}")
        print(f"  ---")
        print(f"  Agree (success):    {stats['agree_success']}")
        print(f"  Agree (ignored):    {stats['agree_ignored']}")
        print(f"  Unit=Y, LLM=N (FP?): {stats['unit_yes_llm_no']}")
        print(f"  Unit=N, LLM=Y (FN?): {stats['unit_no_llm_yes']}")
        print(f"  Agreement rate:     {agreement_pct:.1f}%")

        for k in ("agree_success", "agree_ignored", "unit_yes_llm_no",
                   "unit_no_llm_yes", "unit_no_test", "llm_technical", "total"):
            grand_totals[k] += stats.get(k, 0)
        all_disagreements.extend(stats.get("disagreements", []))

    # Grand totals
    gt = grand_totals
    tested = gt["total"] - gt["llm_technical"] - gt["unit_no_test"]
    agree = gt["agree_success"] + gt["agree_ignored"]
    pct = (agree / tested * 100) if tested > 0 else 0

    print(f"\n{'='*60}")
    print(f"  GRAND TOTALS")
    print(f"{'='*60}")
    print(f"  Total sandboxes:    {gt['total']}")
    print(f"  LLM technical:      {gt['llm_technical']}")
    print(f"  No unit test:       {gt['unit_no_test']}")
    print(f"  Testable:           {tested}")
    print(f"  ---")
    print(f"  Agree (success):    {gt['agree_success']}")
    print(f"  Agree (ignored):    {gt['agree_ignored']}")
    print(f"  Unit=Y, LLM=N (FP?): {gt['unit_yes_llm_no']}")
    print(f"  Unit=N, LLM=Y (FN?): {gt['unit_no_llm_yes']}")
    print(f"  Agreement rate:     {pct:.1f}%")

    if args.show_disagreements and all_disagreements:
        print(f"\n{'='*60}")
        print(f"  DISAGREEMENTS ({len(all_disagreements)} total)")
        print(f"{'='*60}")

        # Group by type
        by_type = defaultdict(list)
        for d in all_disagreements:
            by_type[d["type"]].append(d)

        for dtype, items in sorted(by_type.items()):
            print(f"\n  --- {dtype} ({len(items)}) ---")
            # Group by injection_id
            by_inj = defaultdict(list)
            for item in items:
                by_inj[item["injection_id"]].append(item)
            for iid, inj_items in sorted(by_inj.items()):
                print(f"    INST-{iid} ({len(inj_items)} sandboxes):")
                for item in inj_items[:3]:
                    print(f"      {item['sandbox']}: {item['unit_reason'][:90]}")
                if len(inj_items) > 3:
                    print(f"      ... and {len(inj_items)-3} more")


if __name__ == "__main__":
    main()
