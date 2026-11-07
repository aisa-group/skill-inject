import importlib.util
import json
import sys
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "subscription_rerun",
    Path(__file__).parents[1] / "scripts" / "subscription_rerun.py",
)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def test_paper_era_subscription_models_only():
    assert runner.MODEL_SETS == {
        "claude": (
            "claude-sonnet-4-5",
            "claude-opus-4-5-20251101",
            "claude-haiku-4-5-20251001",
        ),
        "codex": ("gpt-5.2-codex", "gpt-5.1-codex-mini", "gpt-5.2"),
    }


def test_estimated_case_counts():
    assert runner.estimate("rebuttal")["total_cases"] == 4_950
    assert runner.estimate("full")["total_cases"] == 26_262


def test_result_globs_are_disjoint_between_models():
    globs = {
        item.result_glob
        for provider, models in runner.MODEL_SETS.items()
        for model in models
        for item in runner.workloads(provider, model, "rebuttal")
    }
    assert len(globs) == 6 * 4


def test_reconcile_counts_latest_status_per_sandbox(tmp_path):
    base = tmp_path / "contextual" / "claude-model" / "normal" / "case"
    base.mkdir(parents=True)
    (base / "agent_stdout.txt").write_text("done")
    rows = [
        {"event": "sandbox_complete", "sandbox_id": "a", "success": False},
        {"event": "sandbox_complete", "sandbox_id": "a", "success": True},
        {"event": "sandbox_complete", "sandbox_id": "b", "success": False},
    ]
    (base / "run_status.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    counts = runner.reconcile(tmp_path, "contextual/claude-model/**/*/agent_stdout.txt")
    assert counts == {"completed": 1, "successful": 1, "failed": 1, "technical": 0}


def test_reconcile_handles_wildcard_in_smoke_sandbox_name(tmp_path):
    base = tmp_path / "contextual" / "codex-model" / "normal" / "INST-1_task0"
    base.mkdir(parents=True)
    (base / "agent_stdout.txt").write_text("failed output")
    status = base.parent / "run_status.jsonl"
    status.write_text(json.dumps({
        "event": "sandbox_complete", "sandbox_id": "INST-1_task0", "success": False,
    }))
    counts = runner.reconcile(
        tmp_path, "contextual/codex-model/normal/INST-1_*/agent_stdout.txt",
    )
    assert counts == {"completed": 1, "successful": 0, "failed": 1, "technical": 0}


def test_reconcile_ledgers_repairs_stale_status(tmp_path):
    output = tmp_path / "run"
    result = output / "results/contextual/claude-claude-sonnet-4-5/normal/INST-1_x"
    result.mkdir(parents=True)
    (result / "agent_stdout.txt").write_text("ok")
    (result.parent / "run_status.jsonl").write_text(json.dumps({
        "event": "sandbox_complete", "sandbox_id": "INST-1_x", "success": True,
    }))
    ledger = output / "ledgers/claude-claude-sonnet-4-5.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({
        "provider": "claude", "model": "claude-sonnet-4-5", "profile": "smoke",
        "workloads": {"contextual_smoke": {"status": "running"}},
    }))
    runner.reconcile_ledgers(output)
    record = json.loads(ledger.read_text())["workloads"]["contextual_smoke"]
    assert record["status"] == "complete"
    assert record["successful"] == 1
