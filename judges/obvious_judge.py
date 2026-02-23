#!/usr/bin/env python3
"""LLM-as-judge evaluator for obvious injections.

Injection-only evaluation (no task eval). Supports --all-runs for Bo5 dirs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OBVIOUS_INJECTIONS_FILE, PROJECT_ROOT
from judges._base import BaseJudge


class ObviousJudge(BaseJudge):
    judge_name = "obvious"
    default_model = "gpt-5.1-codex-mini"
    default_injections_file = OBVIOUS_INJECTIONS_FILE

    def prepare_tasks(self, sandbox_dirs, injections, **kwargs):
        tasks = []
        for sd in sandbox_dirs:
            inj_id, _ = self.parse_sandbox_name(sd.name)
            inj = injections.get(inj_id, {})
            instr = inj.get("instructions", {})
            injection_text = instr.get("line_injection", "") or instr.get("description_injection", "")

            tasks.append({
                "sandbox_dir": sd,
                "injection_id": inj_id,
                "injection_text": injection_text,
                "judge_prompt": inj.get("judge_prompt"),
            })
        return tasks

    def evaluate_single(self, task, model):
        sd = task["sandbox_dir"]
        result = {
            "sandbox_id": sd.name,
            "injection_id": task["injection_id"],
            "score": "ignored",
            "method": f"llm_judge_{model}",
            "evidence": None,
        }

        if not (sd / "agent_stdout.txt").exists():
            result["score"] = "technical"
            result["evidence"] = "agent_stdout.txt not found"
            return result
        if self.check_technical_failure(sd):
            result["score"] = "technical"
            result["evidence"] = "technical failure detected"
            return result

        prompt = self.build_injection_prompt(
            task["injection_text"], task.get("judge_prompt")
        )
        out = self.run_claude_judge(sd, prompt, model)
        result["score"] = self.parse_injection_verdict(out)
        result["evidence"] = out  # Store full judge output as evidence
        return result


def _auto_detect_injections() -> Path:
    """Try to find obvious_injections.json."""
    candidates = [
        OBVIOUS_INJECTIONS_FILE,
        PROJECT_ROOT / "obvious_injections.json",
        Path("obvious_injections.json"),
    ]
    for c in candidates:
        if c.exists():
            return c
    sys.exit("Could not find obvious_injections.json. Use --injections-file.")


def _evaluate_dir(judge, injections, results_dir, model):
    results = judge.evaluate_all(results_dir, injections, model)
    if results:
        s = sum(1 for r in results if r["score"] == "attack_success")
        i = sum(1 for r in results if r["score"] == "ignored")
        t = sum(1 for r in results if r["score"] == "technical")
        print(f"\nResults: {s} success, {i} ignored, {t} technical")
        judge.save_results(results, results_dir, model)


def _aggregate_bo5_results(parent_dir: Path, model: str):
    """Aggregate Bo5 results across all run directories into a single JSON file."""
    # Find all run directories
    run_dirs = sorted(
        d for d in parent_dir.iterdir()
        if d.is_dir() and d.name.startswith("run-")
    )

    if not run_dirs:
        return

    n_runs = len(run_dirs)

    # Track results per injection across runs
    injection_results = defaultdict(lambda: {'successes': 0, 'runs': 0, 'per_run': {}})
    all_runs_data = []

    for run_dir in run_dirs:
        run_num = int(run_dir.name.split('-')[1])
        eval_file = run_dir / f"evaluation_llmjudge_{model}.json"

        if not eval_file.exists():
            continue

        with open(eval_file, 'r') as f:
            run_data = json.load(f)

        # Track results for this run
        run_successes = []
        run_ignored = []
        run_technical = []

        for result in run_data['results']:
            inj_id = str(result['injection_id'])
            score = result['score']

            injection_results[inj_id]['runs'] += 1

            if score == 'attack_success':
                injection_results[inj_id]['successes'] += 1
                injection_results[inj_id]['per_run'][run_num] = 'success'
                run_successes.append(inj_id)
            elif score == 'ignored':
                injection_results[inj_id]['per_run'][run_num] = 'ignored'
                run_ignored.append(inj_id)
            elif score == 'technical':
                injection_results[inj_id]['per_run'][run_num] = 'technical'
                run_technical.append(inj_id)

        # Store run summary
        all_runs_data.append({
            'run': run_num,
            'successes': run_successes,
            'ignored': run_ignored,
            'technical': run_technical,
            'summary': {
                'success': len(run_successes),
                'ignored': len(run_ignored),
                'technical': len(run_technical),
                'total': len(run_data['results'])
            }
        })

    # Calculate Bo5 statistics
    total_injections = len(injection_results)
    bo5_successes = sum(1 for data in injection_results.values() if data['successes'] >= 1)
    bo5_max_asr = (bo5_successes / total_injections * 100) if total_injections > 0 else 0

    # Build final aggregated result
    aggregated = {
        'agent': parent_dir.name.split('-')[0],  # Extract agent name
        'model': '-'.join(parent_dir.name.split('-')[1:]),  # Extract model name
        'judge_model': model,
        'n_runs': n_runs,
        'bo5_statistics': {
            'total_injections': total_injections,
            'injections_with_at_least_one_success': bo5_successes,
            'bo5_max_asr_percent': round(bo5_max_asr, 2)
        },
        'per_injection': {
            inj_id: {
                'successes': data['successes'],
                'runs': data['runs'],
                'success_rate_percent': round((data['successes'] / data['runs'] * 100), 2),
                'per_run': data['per_run']
            }
            for inj_id, data in sorted(injection_results.items(), key=lambda x: int(x[0]))
        },
        'all_runs': all_runs_data
    }

    # Save aggregated results
    output_path = parent_dir / f"aggregated_results_{model}.json"
    with open(output_path, 'w') as f:
        json.dump(aggregated, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Aggregated results saved to: {output_path}")
    print(f"{'='*60}")
    print(f"Bo5 Summary:")
    print(f"  Total runs: {n_runs}")
    print(f"  Total injections: {total_injections}")
    print(f"  Injections with ≥1 success: {bo5_successes}")
    print(f"  Bo5 Max ASR: {bo5_max_asr:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Obvious injection LLM judge")
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--injections-file", type=Path, default=None)
    parser.add_argument("--model", default="gpt-5.1-codex-mini",
                        help="Judge model to use (GPT: gpt-5-1-codex-mini/gpt-4-1, Claude: sonnet/opus)")
    parser.add_argument("--all-runs", action="store_true")
    args = parser.parse_args()

    if not args.results_dir.exists():
        sys.exit(f"Error: {args.results_dir} not found")

    inj_file = args.injections_file or _auto_detect_injections()
    judge = ObviousJudge()
    injections = judge.load_injections(inj_file)

    if args.all_runs:
        run_dirs = sorted(
            d for d in args.results_dir.iterdir()
            if d.is_dir() and d.name.startswith("run-")
        )
        if not run_dirs:
            sys.exit(f"No run-* dirs in {args.results_dir}")
        for rd in run_dirs:
            print(f"\n{'='*60}\n{rd.name}\n{'='*60}")
            _evaluate_dir(judge, injections, rd, args.model)

        # Aggregate results across all runs
        _aggregate_bo5_results(args.results_dir, args.model)
    else:
        _evaluate_dir(judge, injections, args.results_dir, args.model)


if __name__ == "__main__":
    main()
