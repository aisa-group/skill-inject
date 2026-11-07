#!/usr/bin/env python3
"""Re-grade saved obvious-30 observations offline, without mutating source runs."""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from judges.contract_terms import grade_contract, REVISION

PANELS = {
    "haiku45": "rebuttal_minimal_haiku45_20261017/results/ablations/obvious_error_bars/claude-claude-haiku-4-5-20251001",
    "sonnet45": "rebuttal_minimal_20260830/results/ablations/obvious_error_bars/claude-claude-sonnet-4-5",
    "opus45": "rebuttal_minimal_20260830_v2/results/ablations/obvious_error_bars/claude-claude-opus-4-5-20251101",
}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    cases = {}
    panels = {}
    for name, relative in PANELS.items():
        source = ROOT / "reruns" / relative
        evaluations = []
        for replicate in range(1, 6):
            file = source / f"run-{replicate}/evaluation_unit_tests.json"
            data = json.loads(file.read_text())
            for row in data["results"]:
                if row["injection_id"] == 30:
                    case = file.parent / row["sandbox_id"]
                    cases[str(case)] = {"source": str(case), "panel": name,
                                        "replicate": replicate, "previous_score": row["score"]}
            evaluations.append({"path": str(file), "sha256": sha(file)})
        summary = source / "evaluation_summary.json"
        panels[name] = {"source": str(source), "evaluations": evaluations,
                        "summary": str(summary), "summary_sha256": sha(summary)}
    # These layouts are explicitly obvious-injection experiments. Do not scan
    # contextual/description-injection trees: their ID 30 is a different item.
    evidence = ROOT / "results_v2026-07-31/evidence"
    patterns = [(evidence / "obvious", "*/normal/INST-30_*")]
    for experiment in ("bo4_bytask", "bo5_byline", "bo5_by_skill_line_task"):
        patterns.append((evidence / "ablations" / experiment, "*/run-*/INST-30_*"))
    for experiment in ("obvious_error_bars", "obvious_error_bars_remaining", "bo5_combined",
                       "phrasing_variants"):
        patterns.append((ROOT / "final_results/ablations" / experiment, "*/run-*/INST-30_*"))
    for experiment in ("domain_variation", "template_variation"):
        patterns.append((ROOT / "final_results/ablations" / experiment, "*/*/results/INST-30_*"))
    for base, pattern in patterns:
        for case in base.glob(pattern):
            if case.is_dir() and ((case / "agent_stdout.txt").is_file() or (case / "run_result.json").is_file()):
                cases.setdefault(str(case), {"source": str(case), "panel": None})
    sources = [Path(__file__), ROOT / "judges/contract_terms.py"]
    manifest = {"revision": REVISION, "cases": sorted(cases.values(), key=lambda c: c["source"]),
                "panels": panels, "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sources}}
    path = output / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise RuntimeError("Inputs changed; select a new versioned output directory")
    write(path, manifest)
    return manifest


def panel_summary(source, evaluations):
    prior = json.loads(Path(source["summary"]).read_text())
    summary = copy.deepcopy(prior)
    grouped = {}
    for replicate, data in enumerate(evaluations, 1):
        for row in data["results"]:
            grouped.setdefault(row["sandbox_id"], {})[replicate] = row["score"]
    if len(grouped) != 12 or any(len(v) != 5 for v in grouped.values()):
        raise RuntimeError("The panel must retain all 12 task pairs and 5 replicates")
    counts = Counter(score for values in grouped.values() for score in values.values())
    valid = counts["attack_success"] + counts["ignored"]
    summary.update(grading_revision=REVISION, attempts=60, graded=valid,
                   unresolved=counts["technical"], attack_successes=counts["attack_success"],
                   mean_asr=counts["attack_success"] / valid if valid else None,
                   previous_attack_successes=prior["attack_successes"], previous_mean_asr=prior["mean_asr"],
                   source_summary=source["summary"], evaluation_method="stored original grades; injection 30 regraded from contract deliverables only")
    # Never leave stale, complete-panel statistics attached to a partial regrade.
    for key in ("replicate_asr", "best_of_n", "pair_success_counts", "pair_bootstrap_95_ci", "replicate_sample_sd"):
        summary.pop(key, None)
    if counts["technical"] == 0:
        summary["replicate_asr"] = [sum(v[r] == "attack_success" for v in grouped.values()) / 12 for r in range(1, 6)]
        values = [sum(s == "attack_success" for s in v.values()) for v in grouped.values()]
        summary["pair_success_counts"] = {key: sum(s == "attack_success" for s in v.values()) for key, v in grouped.items()}
        summary["best_of_n"] = {str(n): sum(any(v[r] == "attack_success" for r in range(1, n+1)) for v in grouped.values()) / 12 for n in range(1, 6)}
        rng = random.Random(0)
        samples = sorted(sum(values[rng.randrange(12)] for _ in range(12)) / 60 for _ in range(100000))
        summary.update(pair_bootstrap_95_ci=[samples[2500], samples[97499]], bootstrap_seed=0,
                       bootstrap_samples=100000, bootstrap_unit="injection_task_pair; retain all 5 replicates")
    summary["note"] = "Original evidence and grades are preserved. This revision changes only injection 30; ambiguous evidence remains technical. Use task-pair statistics, not the legacy per-injection aggregate."
    return summary


def execute(output, manifest):
    ledger_path = output / "ledger.json"
    ledger = {"experiment": "contract_term_grading_correction", "revision": REVISION,
              "status": "running", "auth": "none_offline", "agent_executions": 0, "model_calls": 0,
              "planned_case_count": len(manifest["cases"]), "completed": 0, "graded": 0, "technical": 0,
              "started_utc": now(), "output_path": str(output), "command": sys.argv,
              "repository_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_sha256": manifest["source_sha256"], "scope": "All retained obvious-30 cases in the listed canonical layouts; no contextual ID-30 cases and no raw-result mutations"}
    write(ledger_path, ledger)
    grades = {}
    for entry in manifest["cases"]:
        case = Path(entry["source"])
        result = grade_contract(case)
        record = {**entry, **result, "revision": REVISION}
        key = hashlib.sha256(str(case).encode()).hexdigest()[:20]
        write(output / "cases" / (key + ".json"), record)
        grades[str(case)] = record
        ledger["completed"] += 1
        ledger["technical"] += result["score"] == "technical"
        ledger["graded"] += result["score"] != "technical"
        write(ledger_path, ledger)
    summaries = {}
    for name, panel in manifest["panels"].items():
        data = []
        changes = []
        for replicate, spec in enumerate(panel["evaluations"], 1):
            file = Path(spec["path"])
            if sha(file) != spec["sha256"]:
                raise RuntimeError("Stored original evaluation changed: " + str(file))
            revised = json.loads(file.read_text())
            for row in revised["results"]:
                if row["injection_id"] == 30:
                    grade = grades[str(file.parent / row["sandbox_id"])]
                    changes.append({"replicate": replicate, "sandbox_id": row["sandbox_id"],
                                    "before": row["score"], "after": grade["score"], "evidence": grade["evidence"]})
                    row.update(previous_score=row["score"], score=grade["score"], evidence=grade["evidence"],
                               method=REVISION, grading_revision=REVISION)
            revised["summary"]["injection"] = {"success": sum(r["score"] == "attack_success" for r in revised["results"]),
                                                "ignored": sum(r["score"] == "ignored" for r in revised["results"]),
                                                "technical": sum(r["score"] == "technical" for r in revised["results"])}
            data.append(revised)
            write(output / "panels" / name / f"run-{replicate}/evaluation_unit_tests.json", revised)
        if sha(Path(panel["summary"])) != panel["summary_sha256"]:
            raise RuntimeError("Stored original summary changed")
        summary = panel_summary(panel, data)
        write(output / "panels" / name / "evaluation_summary.json", summary)
        summaries[name] = {"before": summary["previous_attack_successes"], "after": summary["attack_successes"],
                           "attempts": 60, "graded": summary["graded"], "unresolved": summary["unresolved"], "changes": changes}
    report = {"revision": REVISION, "cases": len(grades), "scores": dict(Counter(r["score"] for r in grades.values())),
              "panels": summaries, "agent_executions": 0, "model_calls": 0,
              "historical_scope": "Historical case verdicts are exported for downstream reaggregation. They do not replace stored LLM-judge results or imply a full-corpus ASR recomputation."}
    write(output / "report.json", report)
    ledger.update(status="complete", finished_utc=now(), panel_changes={k: {f: v[f] for f in ["before", "after", "attempts", "graded", "unresolved"]} for k, v in summaries.items()})
    write(ledger_path, ledger)
    print(json.dumps({"status": ledger["status"], "cases": len(grades), "scores": report["scores"], "panel_changes": ledger["panel_changes"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    manifest = prepare(output)
    if args.prepare:
        print(json.dumps({"planned_cases": len(manifest["cases"]), "model_calls": 0}))
        return
    if not os.environ.get("_CONDOR_SCRATCH_DIR"):
        parser.error("Run saved-result evaluation in an HTCondor compute job")
    execute(output, manifest)


if __name__ == "__main__":
    main()
