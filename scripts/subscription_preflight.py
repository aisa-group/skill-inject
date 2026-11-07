#!/usr/bin/env python3
"""Check paper-model access through subscription CLIs, without benchmark runs.

Run on a compute node. Each selected model gets one benign, tool-free prompt.
An immutable directory per invocation retains outputs and a resumable ledger.
There is no API-key, model-substitution, or LLM-judge fallback.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "claude": (
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5",
        "claude-opus-4-5-20251101",
    ),
    "codex": ("gpt-5.2-codex", "gpt-5.1-codex-mini", "gpt-5.2"),
}
MARKER = "SUBSCRIPTION_PREFLIGHT_OK"
PROMPT = f"Do not use tools or read files. Reply with exactly {MARKER}."


def subscription_env(source: dict[str, str]) -> dict[str, str]:
    """Only operating-system and network-proxy settings reach the launcher."""
    allowed = {
        "HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "LC_ALL",
        "TMPDIR", "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    }
    env = {key: value for key, value in source.items() if key in allowed}
    env.update(no_proxy="localhost,127.0.0.1,::1,localnet",
               NO_PROXY="localhost,127.0.0.1,::1,localnet")
    return env


def verdict(provider: str, returncode: int, stdout: str, stderr: str) -> str:
    combined = (stdout + "\n" + stderr).lower()
    if "not supported" in combined or "model_not_found" in combined:
        return "model_unavailable"
    if any(term in combined for term in (
        "oauth token has been revoked", "token expired", "failed to authenticate",
        "subscription credentials not found", "authentication_error", "401",
    )):
        return "authentication_failed"
    if any(term in combined for term in ("rate_limit", "rate limit", "usage limit")):
        return "rate_limited"
    if returncode == 124:
        return "timed_out"
    if returncode != 0:
        return "failed"
    if provider == "claude":
        return "passed" if stdout.strip() == MARKER else "unexpected_response"
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    if any(event.get("type") in {"turn.failed", "error"} for event in events):
        return "failed"
    complete = any(event.get("type") == "turn.completed" for event in events)
    message = any(
        event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "agent_message"
        and event["item"].get("text", "").strip() == MARKER
        for event in events
    )
    return "passed" if complete and message else "unexpected_response"


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def cancelled_by_campaign(output: Path, model: str) -> bool:
    selection = output.resolve().parent / "model_selection.json"
    if not selection.exists():
        return False
    scope = json.loads(selection.read_text())
    return model not in scope["active_models"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=MODELS, required=True)
    parser.add_argument("--model", help="Check only this pinned model")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    models = MODELS[args.provider]
    if args.model:
        if args.model not in models:
            parser.error("--model must be a pinned model for the selected provider")
        models = (args.model,)
    if not args.execute:
        print(json.dumps({"auth": "subscription", "models": models,
                          "prompts": len(models), "benchmark_runs": 0}, indent=2))
        return 0
    if not os.environ.get("_CONDOR_SCRATCH_DIR"):
        parser.error("--execute must run in an HTCondor compute job")
    # The enclosing campaign may cancel later model stages while its current
    # model is still running. This file is read by each fresh preflight process,
    # so cancelled stages never reach authentication or a model invocation.
    if any(cancelled_by_campaign(args.output, model) for model in models):
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / "cancelled_stage.json", {
            "status": "cancelled_by_user", "models": list(models),
            "model_calls": 0, "reason": "Campaign model_selection.json excludes this stage"})
        print("Cancelled model stage; no model calls made", flush=True)
        return 78
    root = args.output.resolve() / args.provider
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
        "auth": "subscription", "provider": args.provider,
        "benchmark_runs": 0, "models": {},
        "repository_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "launcher_sha256": hashlib.sha256(
            (ROOT / "apptainer/run_sandbox.sh").read_bytes()).hexdigest(),
    }
    env = subscription_env(dict(os.environ))
    env["TMPDIR"] = os.environ["_CONDOR_SCRATCH_DIR"]
    for model in models:
        if model in ledger["models"]:
            print(model, ledger["models"][model]["status"], "(recorded)", flush=True)
            continue
        run = root / model
        workspace = run / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        command = ["bash", str(ROOT / "apptainer/run_sandbox.sh"),
                   str(ROOT / "apptainer/instruct-bench-agent.sif"),
                   str(workspace), args.provider, PROMPT,
                   str(args.timeout), model, "subscription"]
        start = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, env=env,
                                capture_output=True, text=True)
        (run / "stdout.txt").write_text(result.stdout)
        (run / "stderr.txt").write_text(result.stderr)
        status = verdict(args.provider, result.returncode, result.stdout, result.stderr)
        ledger["models"][model] = {
            "status": status, "returncode": result.returncode,
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stdout": str(run / "stdout.txt"), "stderr": str(run / "stderr.txt"),
        }
        write_json(ledger_path, ledger)
        print(model, status, flush=True)
    return 0 if all(ledger["models"][model]["status"] == "passed" for model in models) else 1


if __name__ == "__main__":
    raise SystemExit(main())
