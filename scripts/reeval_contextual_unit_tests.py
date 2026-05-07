#!/usr/bin/env python3
"""Re-evaluate contextual-injection sandbox runs with the contextual unit tests.

Mirrors scripts/reeval_unit_tests.py but for INST-{inj_id}_task{task_idx} sandboxes
under HOME_RESULTS / "contextual" and HOME_RESULTS / "ablations" / "contextual_*".
Per-injection rollup matches the obvious runner; per-task results are also recorded.

Forward-looking: contextual sandbox runs may not exist yet, in which case the
runner prints "no INST-* sandboxes" for missing dirs and writes an empty summary.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parent.parent))
HOME_RESULTS = Path(os.environ.get("HOME_RESULTS", PROJECT_ROOT / "final_results"))
UNIT_TESTS_DIR = PROJECT_ROOT / "data" / "instruction_unit_tests" / "contextual"
OUT_BASE = PROJECT_ROOT / "final_results" / "reeval_contextual_unit_tests_2026-05-06"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "data" / "instruction_unit_tests"))

from judges._base import BaseJudge  # noqa: E402


def load_test(injection_id: int):
    test_file = UNIT_TESTS_DIR / f"test_contextual_{injection_id}.py"
    if not test_file.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"test_contextual_{injection_id}", test_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "test_attack", None)


def evaluate_dir(sandbox_root: Path) -> dict | None:
    sandboxes = sorted(d for d in sandbox_root.iterdir() if d.is_dir() and d.name.startswith("INST-"))
    if not sandboxes:
        return None

    results = []
    for sd in sandboxes:
        inj_id, task_idx = BaseJudge.parse_sandbox_name(sd.name)
        if not (sd / "agent_stdout.txt").exists():
            results.append({
                "sandbox_id": sd.name, "injection_id": inj_id, "task_idx": task_idx,
                "score": "technical", "method": "unit_test",
                "evidence": "agent_stdout.txt not found",
            })
            continue

        test_fn = load_test(inj_id)
        if test_fn is None:
            results.append({
                "sandbox_id": sd.name, "injection_id": inj_id, "task_idx": task_idx,
                "score": "technical", "method": "unit_test",
                "evidence": f"No unit test for injection {inj_id}",
            })
            continue
        try:
            success, reason = test_fn(sd)
        except Exception as e:
            success, reason = False, f"ERROR: {e}"
        results.append({
            "sandbox_id": sd.name, "injection_id": inj_id, "task_idx": task_idx,
            "score": "attack_success" if success else "ignored",
            "method": "unit_test", "evidence": reason,
        })

    summary = {
        "injection": {
            "success": sum(1 for r in results if r["score"] == "attack_success"),
            "ignored": sum(1 for r in results if r["score"] == "ignored"),
            "technical": sum(1 for r in results if r["score"] == "technical"),
            "total": len(results),
        }
    }
    return {"model": "unit_test", "results": results, "summary": summary}


def write_eval(eval_data: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "evaluation_unit_tests.json"
    out_file.write_text(json.dumps(eval_data, indent=2) + "\n", encoding="utf-8")
    return out_file


def aggregate_runs(model_dir_src: Path, run_evals: list[tuple[int, dict]]) -> dict:
    per_injection: dict[str, dict] = defaultdict(
        lambda: {"successes": 0, "runs": 0, "per_run": {}, "technical": 0}
    )
    per_inj_task: dict[str, dict] = defaultdict(
        lambda: {"successes": 0, "runs": 0, "per_run": {}, "technical": 0}
    )

    all_runs_data = []
    for run_idx, ev in run_evals:
        succ, ign, tech = [], [], []
        for r in ev["results"]:
            iid = str(r["injection_id"])
            tid = r.get("task_idx")
            score = r["score"]
            per_injection[iid]["runs"] += 1
            key_t = f"{iid}_{tid}" if tid is not None else iid
            per_inj_task[key_t]["runs"] += 1
            if score == "attack_success":
                per_injection[iid]["successes"] += 1
                per_injection[iid]["per_run"][run_idx] = "success"
                per_inj_task[key_t]["successes"] += 1
                per_inj_task[key_t]["per_run"][run_idx] = "success"
                succ.append(iid)
            elif score == "ignored":
                per_injection[iid]["per_run"][run_idx] = "ignored"
                per_inj_task[key_t]["per_run"][run_idx] = "ignored"
                ign.append(iid)
            else:
                per_injection[iid]["technical"] += 1
                per_injection[iid]["per_run"][run_idx] = "technical"
                per_inj_task[key_t]["technical"] += 1
                per_inj_task[key_t]["per_run"][run_idx] = "technical"
                tech.append(iid)
        all_runs_data.append({
            "run": run_idx,
            "summary": {
                "success": len(succ), "ignored": len(ign), "technical": len(tech),
                "total": len(ev["results"]),
            },
        })

    total = len(per_injection)
    bo_succ = sum(1 for v in per_injection.values() if v["successes"] >= 1)

    per_run_asr = []
    for run_idx, ev in run_evals:
        s = ev["summary"]["injection"]["success"]
        n = ev["summary"]["injection"]["total"]
        per_run_asr.append({"run": run_idx, "asr": (s / n) if n else 0.0,
                            "success": s, "total": n})

    return {
        "source": str(model_dir_src),
        "n_runs": len(run_evals),
        "total_injections": total,
        "bo_n_max_asr_percent": round((bo_succ / total * 100) if total else 0, 2),
        "per_injection": {
            iid: {
                "successes": d["successes"],
                "runs": d["runs"],
                "asr_percent": round((d["successes"] / d["runs"] * 100) if d["runs"] else 0, 2),
                "per_run": d["per_run"],
            }
            for iid, d in sorted(per_injection.items(), key=lambda x: int(x[0]))
        },
        "per_inj_task": {
            k: {
                "successes": d["successes"],
                "runs": d["runs"],
                "asr_percent": round((d["successes"] / d["runs"] * 100) if d["runs"] else 0, 2),
                "per_run": d["per_run"],
            }
            for k, d in sorted(per_inj_task.items())
        },
        "per_run_asr": per_run_asr,
        "all_runs_summary": all_runs_data,
    }


def process_error_bars_model(model_dir: Path, mirror_dir: Path, label: str):
    run_dirs = sorted(d for d in model_dir.iterdir()
                      if d.is_dir() and d.name.startswith("run-"))
    if not run_dirs:
        print(f"  [skip] {label}/{model_dir.name}: no run-* dirs")
        return

    run_evals: list[tuple[int, dict]] = []
    for rd in run_dirs:
        try:
            run_idx = int(rd.name.split("-")[1])
        except (ValueError, IndexError):
            continue
        ev = evaluate_dir(rd)
        if ev is None:
            print(f"  [skip] {label}/{model_dir.name}/{rd.name}: no INST-* sandboxes")
            continue
        out_dir = mirror_dir / rd.name
        write_eval(ev, out_dir)
        s = ev["summary"]["injection"]
        print(f"  {label}/{model_dir.name}/{rd.name}: "
              f"success={s['success']} ignored={s['ignored']} technical={s['technical']} "
              f"total={s['total']}")
        run_evals.append((run_idx, ev))

    if run_evals:
        agg = aggregate_runs(model_dir, run_evals)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        (mirror_dir / "aggregated_results.json").write_text(
            json.dumps(agg, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  [agg] {label}/{model_dir.name}: "
              f"bo{agg['n_runs']}_max_asr={agg['bo_n_max_asr_percent']}%")


def process_contextual_direct(slug_dir: Path, mirror_dir: Path):
    policy_dir = slug_dir / "normal"
    if not policy_dir.is_dir():
        print(f"  [skip] contextual/{slug_dir.name}: no normal/ dir")
        return
    ev = evaluate_dir(policy_dir)
    if ev is None:
        print(f"  [skip] contextual/{slug_dir.name}/normal: no INST-* sandboxes")
        return
    out_dir = mirror_dir / "normal"
    write_eval(ev, out_dir)
    s = ev["summary"]["injection"]
    asr = (s["success"] / s["total"] * 100) if s["total"] else 0.0
    print(f"  contextual/{slug_dir.name}/normal: "
          f"success={s['success']} ignored={s['ignored']} technical={s['technical']} "
          f"total={s['total']} asr={asr:.1f}%")


def main():
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    print(f"Output: {OUT_BASE}\n")

    eb_src = HOME_RESULTS / "ablations" / "contextual_error_bars"
    eb_dst = OUT_BASE / "ablations" / "contextual_error_bars"
    if eb_src.is_dir():
        print("=== contextual_error_bars ===")
        for model_dir in sorted(d for d in eb_src.iterdir() if d.is_dir()):
            if model_dir.name.startswith("_"):
                continue
            process_error_bars_model(model_dir, eb_dst / model_dir.name, "contextual_error_bars")

    ebr_src = HOME_RESULTS / "ablations" / "contextual_error_bars_remaining"
    ebr_dst = OUT_BASE / "ablations" / "contextual_error_bars_remaining"
    if ebr_src.is_dir():
        print("\n=== contextual_error_bars_remaining ===")
        for model_dir in sorted(d for d in ebr_src.iterdir() if d.is_dir()):
            if model_dir.name.startswith("_"):
                continue
            process_error_bars_model(model_dir, ebr_dst / model_dir.name, "contextual_error_bars_remaining")

    ctx_src = HOME_RESULTS / "contextual"
    ctx_dst = OUT_BASE / "contextual"
    if ctx_src.is_dir():
        print("\n=== contextual (canonical) ===")
        for slug_dir in sorted(d for d in ctx_src.iterdir() if d.is_dir()):
            process_contextual_direct(slug_dir, ctx_dst / slug_dir.name)

    print("\n=== Building grand summary ===")
    grand: dict[str, dict] = {}
    for agg_file in sorted(OUT_BASE.rglob("aggregated_results.json")):
        rel = agg_file.relative_to(OUT_BASE)
        try:
            data = json.loads(agg_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        grand[str(rel.parent)] = {
            "n_runs": data.get("n_runs"),
            "total_injections": data.get("total_injections"),
            "bo_n_max_asr_percent": data.get("bo_n_max_asr_percent"),
            "per_run_asr": data.get("per_run_asr"),
        }
    if (OUT_BASE / "contextual").is_dir():
        for ev_file in sorted((OUT_BASE / "contextual").rglob("evaluation_unit_tests.json")):
            rel = ev_file.relative_to(OUT_BASE)
            try:
                data = json.loads(ev_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            s = data.get("summary", {}).get("injection", {})
            total = s.get("total", 0)
            grand[str(rel.parent)] = {
                "single_run": True,
                "success": s.get("success", 0),
                "ignored": s.get("ignored", 0),
                "technical": s.get("technical", 0),
                "total": total,
                "asr_percent": round(s.get("success", 0) / total * 100, 2) if total else 0,
            }

    summary_path = OUT_BASE / "summary.json"
    summary_path.write_text(json.dumps(grand, indent=2) + "\n", encoding="utf-8")
    print(f"\nGrand summary: {summary_path}")
    for k, v in grand.items():
        if v.get("single_run"):
            print(f"  {k}: ASR {v['asr_percent']}% "
                  f"({v['success']}/{v['total']}, tech={v['technical']})")
        else:
            print(f"  {k}: bo{v['n_runs']}_max_asr={v['bo_n_max_asr_percent']}% "
                  f"over {v['total_injections']} inj")


if __name__ == "__main__":
    main()
