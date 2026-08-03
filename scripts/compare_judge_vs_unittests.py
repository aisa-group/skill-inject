#!/usr/bin/env python3
"""Compare the LLM judge against the current (exhaustive) unit-test grader.

For every run directory that carries both graders, this reports:

  * ASR as computed by the LLM judge      (``injection_score``)
  * ASR as computed by the unit tests     (``score`` in evaluation_unittest.json)
  * Utility as computed by the LLM judge  (``task_score``)
  * Utility from the unit tests, when the run carries a task-level grade
  * The number of individual test cases (sandboxes) on which the two disagree

Disagreements are split by direction and by whether the unit test for that case
is self-contained or falls back to the LLM (``llm_dependent_test``).

This deliberately reads ``evaluation_unittest.json`` — the current exhaustive
generation.  ``evaluation_deterministic.json`` is the older, thinner generation
and is only read with --legacy for provenance.

Usage:
    python3 scripts/compare_judge_vs_unittests.py [ROOT] [--json OUT] [--legacy]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = PROJECT_ROOT / "results_v2026-07-31" / "evidence"

# score vocabularies
ATTACK_SUCCESS = "attack_success"
IGNORED = "ignored"
TECHNICAL = "technical"
TASK_SUCCESS = "task_success"
TASK_FAILED = "task_failed"


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt / truncated file
        print(f"  ! unreadable {path}: {exc}", file=sys.stderr)
        return None


def records(blob) -> list[dict]:
    if blob is None:
        return []
    if isinstance(blob, dict):
        return blob.get("results", []) or []
    if isinstance(blob, list):
        return blob
    return []


def judge_files(run_dir: Path) -> list[Path]:
    """LLM judge evaluations, newest-looking first, .backup.json excluded."""
    return sorted(
        f for f in run_dir.glob("evaluation_llmjudge_*.json")
        if not f.name.endswith(".backup.json")
    )


def find_runs(root: Path, legacy: bool) -> list[Path]:
    """Every directory holding a unit-test evaluation and/or an LLM judge one."""
    seen: set[Path] = set()
    patterns = ["evaluation_unittest.json", "evaluation_llmjudge_*.json"]
    if legacy:
        patterns.append("evaluation_deterministic.json")
    for pat in patterns:
        for f in root.rglob(pat):
            if f.name.endswith(".backup.json"):
                continue
            seen.add(f.parent)
    return sorted(seen)


def rate(num: int, den: int):
    return (num / den * 100) if den else None


def fmt(x, suffix="%"):
    return "  —  " if x is None else f"{x:5.1f}{suffix}"


def analyse_run(run_dir: Path, root: Path, legacy: bool) -> dict | None:
    unit = {r["sandbox_id"]: r for r in records(load_json(run_dir / "evaluation_unittest.json"))}
    unit_llm_dep = {sid: bool(r.get("llm_dependent_test")) for sid, r in unit.items()}

    jf = judge_files(run_dir)
    judge: dict[str, dict] = {}
    for f in jf:  # later files win; they are the re-judged ones
        for r in records(load_json(f)):
            judge[r["sandbox_id"]] = r

    legacy_unit = {}
    if legacy:
        legacy_unit = {
            r["sandbox_id"]: r
            for r in records(load_json(run_dir / "evaluation_deterministic.json"))
        }

    if not unit and not judge:
        return None

    # --- per-grader aggregate rates -------------------------------------
    j_att = Counter()
    j_task = Counter()
    for r in judge.values():
        s = r.get("injection_score") or r.get("score")
        j_att[s] += 1
        t = r.get("task_score")
        if t:
            j_task[t] += 1

    u_att = Counter()
    u_task = Counter()
    for r in unit.values():
        u_att[r.get("score")] += 1
        t = r.get("task_score") or r.get("task_result")
        if t:
            u_task[t] += 1

    j_att_den = j_att[ATTACK_SUCCESS] + j_att[IGNORED]
    u_att_den = u_att[ATTACK_SUCCESS] + u_att[IGNORED]
    j_task_den = j_task[TASK_SUCCESS] + j_task[TASK_FAILED]
    u_task_den = u_task[TASK_SUCCESS] + u_task[TASK_FAILED]

    # --- per-case comparison --------------------------------------------
    both = sorted(set(unit) & set(judge))
    cmp_stats = Counter()
    disagreements = []

    for sid in both:
        js = judge[sid].get("injection_score") or judge[sid].get("score")
        us = unit[sid].get("score")

        if js == TECHNICAL or us == TECHNICAL:
            cmp_stats["skipped_technical"] += 1
            continue
        if js not in (ATTACK_SUCCESS, IGNORED) or us not in (ATTACK_SUCCESS, IGNORED):
            cmp_stats["skipped_unscored"] += 1
            continue

        cmp_stats["comparable"] += 1
        jb, ub = js == ATTACK_SUCCESS, us == ATTACK_SUCCESS
        llm_dep = unit_llm_dep.get(sid, False)

        if jb == ub:
            cmp_stats["agree_success" if jb else "agree_ignored"] += 1
            continue

        key = "unit_yes_judge_no" if ub else "unit_no_judge_yes"
        cmp_stats[key] += 1
        cmp_stats[f"{key}__llm_dependent" if llm_dep else f"{key}__self_contained"] += 1
        disagreements.append({
            "run": str(run_dir.relative_to(root)),
            "sandbox_id": sid,
            "injection_id": unit[sid].get("injection_id"),
            "direction": key,
            "llm_dependent_test": llm_dep,
            "unit_evidence": (unit[sid].get("evidence") or "")[:200],
            "judge_evidence": (judge[sid].get("injection_evidence") or "")[:200],
        })

    # --- legacy (old thin unit tests) vs current, for provenance ---------
    legacy_delta = None
    if legacy_unit:
        shared = set(legacy_unit) & set(unit)
        legacy_delta = sum(
            1 for sid in shared
            if (legacy_unit[sid].get("score") == ATTACK_SUCCESS)
            != (unit[sid].get("score") == ATTACK_SUCCESS)
        )

    return {
        "run": str(run_dir.relative_to(root)),
        "judge_files": [f.name for f in jf],
        "n_unit": len(unit),
        "n_judge": len(judge),
        "n_both": len(both),
        "judge_asr": rate(j_att[ATTACK_SUCCESS], j_att_den),
        "unit_asr": rate(u_att[ATTACK_SUCCESS], u_att_den),
        "judge_utility": rate(j_task[TASK_SUCCESS], j_task_den),
        "unit_utility": rate(u_task[TASK_SUCCESS], u_task_den),
        "judge_technical": j_att[TECHNICAL],
        "unit_technical": u_att[TECHNICAL],
        "n_llm_dependent_tests": sum(unit_llm_dep.values()),
        "legacy_vs_current_unit_diffs": legacy_delta,
        **{k: cmp_stats[k] for k in (
            "comparable", "agree_success", "agree_ignored",
            "unit_yes_judge_no", "unit_no_judge_yes",
            "unit_yes_judge_no__self_contained", "unit_yes_judge_no__llm_dependent",
            "unit_no_judge_yes__self_contained", "unit_no_judge_yes__llm_dependent",
            "skipped_technical", "skipped_unscored",
        )},
        "_disagreements": disagreements,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(DEFAULT_ROOT))
    ap.add_argument("--json", help="write the full report (incl. per-case disagreements) here")
    ap.add_argument("--legacy", action="store_true",
                    help="also read evaluation_deterministic.json (old thin unit tests)")
    ap.add_argument("--top", type=int, default=15, help="how many worst runs to list")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.exit(f"No such root: {root}")

    runs = find_runs(root, args.legacy)
    print(f"Scanning {root}\nFound {len(runs)} run directories with evaluation artifacts\n")

    reports = []
    for rd in runs:
        rep = analyse_run(rd, root, args.legacy)
        if rep:
            reports.append(rep)

    paired = [r for r in reports if r["comparable"] > 0]

    hdr = (f"{'run':<62} {'n':>4} {'ASR judge':>10} {'ASR unit':>9} "
           f"{'Util judge':>11} {'Util unit':>10} {'disagree':>9} {'agree%':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(paired, key=lambda x: -(x["unit_yes_judge_no"] + x["unit_no_judge_yes"])):
        dis = r["unit_yes_judge_no"] + r["unit_no_judge_yes"]
        agree = rate(r["comparable"] - dis, r["comparable"])
        print(f"{r['run']:<62} {r['comparable']:>4} {fmt(r['judge_asr']):>10} {fmt(r['unit_asr']):>9} "
              f"{fmt(r['judge_utility']):>11} {fmt(r['unit_utility']):>10} {dis:>9} {fmt(agree):>7}")

    # ---- totals ----
    tot = Counter()
    for r in paired:
        for k in ("comparable", "agree_success", "agree_ignored",
                  "unit_yes_judge_no", "unit_no_judge_yes",
                  "unit_yes_judge_no__self_contained", "unit_yes_judge_no__llm_dependent",
                  "unit_no_judge_yes__self_contained", "unit_no_judge_yes__llm_dependent",
                  "skipped_technical", "skipped_unscored"):
            tot[k] += r[k]

    dis = tot["unit_yes_judge_no"] + tot["unit_no_judge_yes"]
    print("\n" + "=" * 72)
    print("  TOTALS  (test cases = one sandbox in one run)")
    print("=" * 72)
    print(f"  Runs with both graders:            {len(paired)}")
    print(f"  Runs with only one grader:         {len(reports) - len(paired)}")
    print(f"  Comparable test cases:             {tot['comparable']}")
    print(f"  Skipped (technical):               {tot['skipped_technical']}")
    print(f"  Skipped (unscored/missing):        {tot['skipped_unscored']}")
    print("  ---")
    print(f"  Agree — both attack_success:       {tot['agree_success']}")
    print(f"  Agree — both ignored:              {tot['agree_ignored']}")
    print(f"  DISAGREE — total:                  {dis}"
          f"   ({rate(dis, tot['comparable']):.2f}% of comparable)" if tot["comparable"] else "")
    print(f"     unit=success, judge=ignored:    {tot['unit_yes_judge_no']}"
          f"   (self-contained {tot['unit_yes_judge_no__self_contained']},"
          f" llm-dependent {tot['unit_yes_judge_no__llm_dependent']})")
    print(f"     unit=ignored, judge=success:    {tot['unit_no_judge_yes']}"
          f"   (self-contained {tot['unit_no_judge_yes__self_contained']},"
          f" llm-dependent {tot['unit_no_judge_yes__llm_dependent']})")
    print(f"  Agreement rate:                    {rate(tot['comparable'] - dis, tot['comparable']):.2f}%")

    # ---- where do disagreements concentrate ----
    by_inj = Counter()
    for r in paired:
        for d in r["_disagreements"]:
            by_inj[d["injection_id"]] += 1
    if by_inj:
        print("\n  Disagreements by injection id (top 15):")
        for iid, n in by_inj.most_common(15):
            print(f"    INST-{iid:<4} {n}")

    # ---- utility coverage note ----
    with_unit_util = [r for r in paired if r["unit_utility"] is not None]
    print(f"\n  Runs where the unit-test grader also produced a utility/task grade: "
          f"{len(with_unit_util)}/{len(paired)}")

    if args.json:
        out = Path(args.json)
        out.write_text(json.dumps({
            "root": str(root),
            "totals": dict(tot),
            "runs": reports,
        }, indent=1), encoding="utf-8")
        print(f"\n  Full report written to {out}")


if __name__ == "__main__":
    main()
