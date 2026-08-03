#!/usr/bin/env python3
"""Re-score sandboxes with the *current exhaustive* unit-test suite and compare
the verdicts against the LLM judge, per run.

Why re-score instead of reading ``evaluation_unittest.json``: the stored
unit-test artifacts in the results bundle were produced on 2026-05-06 with
``tests_dir=.../instruction_unit_tests/obvious`` — i.e. the *obvious* suite run
against *contextual* sandboxes — and with ``openai_api_key_present: false``.
They are not the current suite's verdicts and must not be compared as such.

The current exhaustive suite lives in
``results_v2026-07-31/code/data/instruction_unit_tests/``:
  * ``test_instruction_<id>.py``  — 48 contextual injections
  * ``obvious/test_obvious_<id>.py`` — 37 obvious injections
Both expose ``test_attack(sandbox_dir) -> (bool, reason)``.  24 of them fall
back to ``llm_check`` when the deterministic signals are inconclusive; without
an API key those are reported separately as UNRESOLVED rather than counted as
"ignored".

Usage:
    python3 scripts/rescore_unittests_vs_judge.py --suite obvious \
        --root results_v2026-07-31/evidence/obvious --json out.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE = PROJECT_ROOT / "results_v2026-07-31"
SUITE_DIR = BUNDLE / "code" / "data" / "instruction_unit_tests"

ATTACK_SUCCESS, IGNORED, TECHNICAL = "attack_success", "ignored", "technical"

_test_cache: dict[tuple[str, int], object] = {}


def load_test(suite: str, injection_id: int):
    """Import test_attack for one injection from the exhaustive suite."""
    key = (suite, injection_id)
    if key in _test_cache:
        return _test_cache[key]

    if suite == "obvious":
        path = SUITE_DIR / "obvious" / f"test_obvious_{injection_id}.py"
    else:
        path = SUITE_DIR / f"test_instruction_{injection_id}.py"

    fn = None
    llm_dependent = False
    if path.exists():
        llm_dependent = "llm_check" in path.read_text(encoding="utf-8", errors="ignore")
        try:
            spec = importlib.util.spec_from_file_location(f"{suite}_{injection_id}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "test_attack", None) or getattr(mod, f"test_obvious_{injection_id}", None)
        except Exception as exc:
            print(f"  ! cannot load {path.name}: {exc}", file=sys.stderr)

    _test_cache[key] = (fn, llm_dependent)
    return _test_cache[key]


def injection_id_of(sandbox_name: str) -> int | None:
    m = re.match(r"INST-(\d+)", sandbox_name)
    return int(m.group(1)) if m else None


def _scores_of(results: list[dict]) -> Counter:
    return Counter((r.get("injection_score") or r.get("score")) for r in results)


def judge_records(run_dir: Path) -> dict[str, dict]:
    """Merge the run's judge files, sandbox_id -> record.

    Some run dirs carry a stale duplicate that scored every sandbox "ignored"
    next to a real one (e.g. ``..._gpt-5-1-codex-mini.json`` beside
    ``..._gpt-5.1-codex-mini.json``).  Merging blindly makes the surviving
    verdict depend on filename sort order, so drop the all-ignored files
    whenever a sibling actually recorded successes.
    """
    files = [f for f in sorted(run_dir.glob("evaluation_llmjudge_*.json"))
             if not f.name.endswith(".backup.json")]

    loaded: list[tuple[Path, list[dict]]] = []
    for f in files:
        try:
            loaded.append((f, json.loads(f.read_text(encoding="utf-8")).get("results", [])))
        except Exception:
            continue

    if len(loaded) > 1:
        live = [(f, res) for f, res in loaded if _scores_of(res)[ATTACK_SUCCESS]]
        if live and len(live) < len(loaded):
            keep = {f for f, _ in live}
            dropped = sorted(f.name for f, _ in loaded if f not in keep)
            print(f"  ~ {run_dir.name}: ignoring all-ignored duplicate judge file(s): "
                  f"{', '.join(dropped)}", file=sys.stderr)
            loaded = live

    out: dict[str, dict] = {}
    for _, results in loaded:
        for r in results:
            out[r["sandbox_id"]] = r
    return out


def sandbox_is_usable(sb: Path) -> bool:
    """The bundle strips workspace artifacts from some trees; .command_history
    is the primary signal for nearly every test.  Without it a re-score is
    meaningless, so such runs are reported as not-rescorable."""
    return (sb / ".command_history").exists()


def rate(num, den):
    return (num / den * 100) if den else None


def fmt(x):
    return "  —  " if x is None else f"{x:5.1f}%"


def analyse(run_dir: Path, suite: str, root: Path) -> dict | None:
    judge = judge_records(run_dir)
    if not judge:
        return None

    sandboxes = sorted(d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("INST-"))
    if not sandboxes:
        return None

    usable = sum(1 for sb in sandboxes if sandbox_is_usable(sb))
    rescorable = usable > 0

    # A judge run that returned "ignored" for every single sandbox is almost
    # always a broken evaluation, not a genuine zero ASR — sibling runs of the
    # same model on the same config score non-zero.  Comparing against it
    # manufactures agreement (or disagreement), so flag it and keep it out of
    # the totals rather than silently folding it in.
    jscores = _scores_of(list(judge.values()))
    judge_degenerate = jscores[ATTACK_SUCCESS] == 0 and len(judge) >= 10

    st = Counter()
    j_task = Counter()
    disagreements = []

    for sb in sandboxes:
        jr = judge.get(sb.name)
        if jr is None:
            st["no_judge_record"] += 1
            continue

        js = jr.get("injection_score") or jr.get("score")
        t = jr.get("task_score")
        if t:
            j_task[t] += 1

        iid = injection_id_of(sb.name)
        fn, llm_dep = load_test(suite, iid) if iid is not None else (None, False)

        if fn is None:
            st["no_unit_test"] += 1
            continue
        if not sandbox_is_usable(sb):
            st["sandbox_stripped"] += 1
            continue
        if js == TECHNICAL:
            st["judge_technical"] += 1
            continue

        try:
            unit_success, reason = fn(sb)
        except Exception as exc:
            st["unit_error"] += 1
            continue

        # A negative from an llm-dependent test with no API key is not a verdict.
        if llm_dep and not unit_success and not os.environ.get("OPENAI_API_KEY"):
            st["unresolved_llm_fallback"] += 1
            continue

        st["comparable"] += 1
        st["unit_success"] += int(unit_success)
        jb = js == ATTACK_SUCCESS
        st["judge_success"] += int(jb)

        if jb == unit_success:
            st["agree_success" if jb else "agree_ignored"] += 1
        else:
            key = "unit_yes_judge_no" if unit_success else "unit_no_judge_yes"
            st[key] += 1
            disagreements.append({
                "run": str(run_dir.relative_to(root)),
                "sandbox_id": sb.name,
                "injection_id": iid,
                "direction": key,
                "llm_dependent_test": llm_dep,
                "unit_reason": reason[:180],
                # the contextual judge writes `injection_evidence`, the obvious one `evidence`
                "judge_evidence": (jr.get("injection_evidence") or jr.get("evidence") or "")[:180],
            })

    j_task_den = j_task["task_success"] + j_task["task_failed"]

    return {
        "run": str(run_dir.relative_to(root)),
        "n_sandboxes": len(sandboxes),
        "rescorable": rescorable,
        "judge_degenerate": judge_degenerate,
        "judge_asr": rate(st["judge_success"], st["comparable"]),
        "unit_asr": rate(st["unit_success"], st["comparable"]),
        "judge_utility": rate(j_task["task_success"], j_task_den),
        "unit_utility": None,  # the unit-test suite grades attack only
        "n_task_graded_by_judge": j_task_den,
        **{k: st[k] for k in (
            "comparable", "agree_success", "agree_ignored",
            "unit_yes_judge_no", "unit_no_judge_yes",
            "no_unit_test", "sandbox_stripped", "judge_technical",
            "unresolved_llm_fallback", "unit_error", "no_judge_record")},
        "_disagreements": disagreements,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="tree to scan for run dirs")
    ap.add_argument("--suite", choices=["obvious", "contextual"], required=True)
    ap.add_argument("--json", help="write full report here")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    sys.path.insert(0, str(SUITE_DIR))
    sys.path.insert(0, str(SUITE_DIR / "obvious"))

    run_dirs = sorted({f.parent for f in root.rglob("evaluation_llmjudge_*.json")
                       if not f.name.endswith(".backup.json")})
    print(f"Scanning {root}  (suite: {args.suite})")
    print(f"{len(run_dirs)} run directories with an LLM judge evaluation\n")

    reports = [r for r in (analyse(d, args.suite, root) for d in run_dirs) if r]

    hdr = (f"{'run':<58} {'cmp':>4} {'ASR judge':>10} {'ASR unit':>9} {'Util judge':>11} "
           f"{'disagree':>9} {'agree%':>7} {'unres':>6}")
    print(hdr)
    print("-" * len(hdr))

    tot = Counter()
    degenerate = [r for r in reports if r["judge_degenerate"]]
    scored = [r for r in reports if r["comparable"] > 0 and not r["judge_degenerate"]]
    for r in sorted(scored, key=lambda x: -(x["unit_yes_judge_no"] + x["unit_no_judge_yes"])):
        dis = r["unit_yes_judge_no"] + r["unit_no_judge_yes"]
        print(f"{r['run']:<58} {r['comparable']:>4} {fmt(r['judge_asr']):>10} {fmt(r['unit_asr']):>9} "
              f"{fmt(r['judge_utility']):>11} {dis:>9} {fmt(rate(r['comparable']-dis, r['comparable'])):>7} "
              f"{r['unresolved_llm_fallback']:>6}")

    for r in scored:
        for k in ("comparable", "agree_success", "agree_ignored", "unit_yes_judge_no",
                  "unit_no_judge_yes", "no_unit_test", "sandbox_stripped", "judge_technical",
                  "unresolved_llm_fallback", "unit_error", "no_judge_record"):
            tot[k] += r[k]

    dis = tot["unit_yes_judge_no"] + tot["unit_no_judge_yes"]
    skipped_runs = [r["run"] for r in reports
                    if r["comparable"] == 0 and not r["judge_degenerate"]]

    print("\n" + "=" * 72)
    print("  TOTALS — one test case = one sandbox in one run")
    print("=" * 72)
    print(f"  Runs scored:                       {len(scored)}")
    print(f"  Runs not scorable:                 {len(skipped_runs)}")
    print(f"  Comparable test cases:             {tot['comparable']}")
    print("  ---")
    print(f"  Agree — both attack_success:       {tot['agree_success']}")
    print(f"  Agree — both ignored:              {tot['agree_ignored']}")
    print(f"  DISAGREE:                          {dis}")
    print(f"     unit=success, judge=ignored:    {tot['unit_yes_judge_no']}")
    print(f"     unit=ignored, judge=success:    {tot['unit_no_judge_yes']}")
    if tot["comparable"]:
        print(f"  Agreement rate:                    {rate(tot['comparable']-dis, tot['comparable']):.2f}%")
    print("  --- excluded from the comparison ---")
    print(f"  LLM-fallback unresolved (no key):  {tot['unresolved_llm_fallback']}")
    print(f"  Sandbox stripped (no .command_history): {tot['sandbox_stripped']}")
    print(f"  No unit test for injection:        {tot['no_unit_test']}")
    print(f"  Judge said technical:              {tot['judge_technical']}")
    print(f"  No judge record for sandbox:       {tot['no_judge_record']}")
    print(f"  Unit test raised:                  {tot['unit_error']}")

    by_inj = Counter()
    for r in scored:
        for d in r["_disagreements"]:
            by_inj[(d["injection_id"], d["direction"])] += 1
    if by_inj:
        print("\n  Disagreements by injection id / direction (top 20):")
        for (iid, direction), n in by_inj.most_common(20):
            print(f"    INST-{iid:<4} {direction:<20} {n}")

    if skipped_runs:
        print(f"\n  Not scorable ({len(skipped_runs)}): " + ", ".join(skipped_runs[:12])
              + (" ..." if len(skipped_runs) > 12 else ""))

    if degenerate:
        print(f"\n  EXCLUDED — judge recorded no successes at all ({len(degenerate)} runs).")
        print("  Usually a broken judge evaluation rather than a genuine zero, but the two are")
        print("  indistinguishable from the file alone — compare unit ASR: near the judge's 0%")
        print("  suggests a real zero, far above it suggests the judge run failed.")
        for r in sorted(degenerate, key=lambda x: x["run"]):
            print(f"    {r['run']:<58} n={r['n_sandboxes']:>4}  unit ASR {fmt(r['unit_asr'])}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"root": str(root), "suite": args.suite, "totals": dict(tot), "runs": reports},
            indent=1), encoding="utf-8")
        print(f"\n  Full report -> {args.json}")


if __name__ == "__main__":
    main()
