#!/usr/bin/env python3
"""LLM-as-judge evaluator for contextual injections.

Evaluates injection success (ASR) and optionally task completion (utility).
Runs evaluations in parallel via BaseJudge.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CONTEXTUAL_INJECTIONS_FILE
from judges._base import BaseJudge


class ContextualJudge(BaseJudge):
    judge_name = "contextual"
    default_model = "gpt-5.1-codex-mini"
    default_injections_file = CONTEXTUAL_INJECTIONS_FILE

    def prepare_tasks(self, sandbox_dirs, injections, **kwargs):
        evaluate_task = kwargs.get("evaluate_task", False)
        evaluate_injection = kwargs.get("evaluate_injection", True)
        tasks = []
        for sd in sandbox_dirs:
            inj_id, task_idx = self.parse_sandbox_name(sd.name)
            inj = injections.get(inj_id, {})
            instr = inj.get("instructions", {})
            injection_text = instr.get("description_injection", "")

            task_prompt = None
            task_destructive = inj.get("task_destructive", False)
            if evaluate_task and task_idx is not None and not task_destructive:
                task_list = inj.get("tasks", [])
                if task_idx < len(task_list):
                    task_prompt = task_list[task_idx].get("prompt", "")

            tasks.append({
                "sandbox_dir": sd,
                "injection_id": inj_id,
                "injection_text": injection_text,
                "judge_prompt": inj.get("judge_prompt"),
                "task_prompt": task_prompt,
                "evaluate_task": evaluate_task,
                "evaluate_injection": evaluate_injection,
            })
        return tasks

    def evaluate_single(self, task, model):
        sd = task["sandbox_dir"]
        result = {
            "sandbox_id": sd.name,
            "injection_id": task.get("injection_id"),
            "injection_score": "ignored",
            "task_score": None,
            "method": f"llm_judge_{model}",
            "injection_evidence": None,
            "task_evidence": None,
        }

        if not (sd / "agent_stdout.txt").exists():
            result["injection_score"] = "technical"
            result["score"] = "technical"
            result["injection_evidence"] = "agent_stdout.txt not found"
            return result

        if self.check_technical_failure(sd):
            result["injection_score"] = "technical"
            result["score"] = "technical"
            result["injection_evidence"] = "technical failure detected"
            return result

        # Injection evaluation (skip if evaluate_injection=False)
        evaluate_injection = task.get("evaluate_injection", True)
        if evaluate_injection:
            prompt = self.build_injection_prompt(
                task["injection_text"], task.get("judge_prompt")
            )
            out = self.run_claude_judge(sd, prompt, model)
            result["injection_score"] = self.parse_injection_verdict(out)
            result["injection_evidence"] = out  # Store full judge output as evidence
        else:
            result["injection_score"] = "not_evaluated"
            result["injection_evidence"] = "injection evaluation skipped"

        # Task evaluation
        if task.get("evaluate_task") and task.get("task_prompt"):
            tp = self.build_task_prompt(task["task_prompt"])
            tout = self.run_claude_judge(sd, tp, model)
            result["task_score"] = self.parse_task_verdict(tout)
            result["task_evidence"] = tout  # Store full judge output as evidence

        result["score"] = result["injection_score"]
        return result


def main():
    parser = argparse.ArgumentParser(description="Contextual injection LLM judge")
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--injections-file", type=Path, default=CONTEXTUAL_INJECTIONS_FILE)
    parser.add_argument("--model", default="sonnet",
                        help="Judge model to use (Claude: sonnet/opus/haiku, GPT: gpt-4-1/gpt-5-1-codex-mini/etc)")
    parser.add_argument("--evaluate-task", action="store_true")
    parser.add_argument("--no-evaluate-injection", action="store_true",
                        help="Skip injection evaluation (for clean utility baseline)")
    args = parser.parse_args()

    if not args.results_dir.exists():
        sys.exit(f"Error: {args.results_dir} not found")

    judge = ContextualJudge()
    injections = judge.load_injections(args.injections_file)
    results = judge.evaluate_all(
        args.results_dir, injections, args.model,
        evaluate_task=args.evaluate_task,
        evaluate_injection=not args.no_evaluate_injection,
    )

    # Summary
    inj_s = sum(1 for r in results if r["injection_score"] == "attack_success")
    inj_i = sum(1 for r in results if r["injection_score"] == "ignored")
    inj_t = sum(1 for r in results if r["injection_score"] == "technical")
    print(f"\nInjection: {inj_s} success, {inj_i} ignored, {inj_t} technical")

    extra = {}
    if args.evaluate_task:
        ts = sum(1 for r in results if r.get("task_score") == "task_success")
        tf = sum(1 for r in results if r.get("task_score") == "task_failed")
        tt = sum(1 for r in results if r.get("task_score") == "technical")
        print(f"Task: {ts} success, {tf} failed, {tt} technical")
        extra["task"] = {"success": ts, "failed": tf, "technical": tt}

    judge.save_results(results, args.results_dir, args.model, **extra)


if __name__ == "__main__":
    main()
