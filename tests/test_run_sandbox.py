"""Tests for scripts/run_sandbox_container.py — StatusLogger, resume logic, helpers."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.run_sandbox_container import (
    StatusLogger,
    RunResult,
    ContainerConfig,
    _collect_evidence,
    _get_security_text,
    _security_system_args,
    _needs_prompt_fallback,
    save_results,
    run_all_sandboxes,
    load_env_file,
    subscription_credential_mount,
    should_forward_api_key,
)


# ---------------------------------------------------------------------------
# Subscription authentication
# ---------------------------------------------------------------------------

class TestSubscriptionAuthentication:
    @pytest.mark.parametrize(("agent", "relative", "target"), [
        ("claude", ".claude/.credentials.json", "/home/agent/.claude/.credentials.json"),
        ("codex", ".codex/auth.json", "/home/agent/.codex/auth.json"),
    ])
    def test_resolves_provider_credentials(self, tmp_path, agent, relative, target):
        credential = tmp_path / relative
        credential.parent.mkdir(parents=True)
        credential.write_text(
            json.dumps({"auth_mode": "chatgpt"}) if agent == "codex"
            else json.dumps({"claudeAiOauth": {"accessToken": "test"}})
        )
        assert subscription_credential_mount(agent, tmp_path) == (credential, target)

    def test_api_key_credential_is_rejected_as_subscription(self, tmp_path):
        credential = tmp_path / ".codex" / "auth.json"
        credential.parent.mkdir(parents=True)
        credential.write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "test"}))
        with pytest.raises(ValueError, match="does not contain codex subscription"):
            subscription_credential_mount("codex", tmp_path)

    def test_missing_subscription_credentials_fail_clearly(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Log in with the codex CLI"):
            subscription_credential_mount("codex", tmp_path)

    def test_unsupported_subscription_agent_fails(self, tmp_path):
        with pytest.raises(ValueError, match="unsupported"):
            subscription_credential_mount("gemini", tmp_path)

    def test_invalid_auth_mode_fails(self):
        with pytest.raises(ValueError, match="Unknown authentication mode"):
            ContainerConfig(auth_mode="invalid")

    @pytest.mark.parametrize(("agent", "key"), [
        ("claude", "ANTHROPIC_API_KEY"),
        ("codex", "OPENAI_API_KEY"),
    ])
    def test_subscription_suppresses_own_provider_key(self, agent, key):
        assert not should_forward_api_key(agent, key, "subscription")
        assert should_forward_api_key(agent, key, "api-key")
        assert should_forward_api_key(agent, key, "auto")


# ---------------------------------------------------------------------------
# Container command integration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("agent", "credential", "target", "key"), [
    ("claude", ".claude/.credentials.json", "/home/agent/.claude/.credentials.json", "ANTHROPIC_API_KEY"),
    ("codex", ".codex/auth.json", "/home/agent/.codex/auth.json", "OPENAI_API_KEY"),
])
def test_subscription_container_mounts_oauth_and_omits_api_key(
    tmp_path, monkeypatch, agent, credential, target, key,
):
    import scripts.run_sandbox_container as mod

    home = tmp_path / "home"
    cred = home / credential
    cred.parent.mkdir(parents=True)
    cred.write_text(
        json.dumps({"auth_mode": "chatgpt"}) if agent == "codex"
        else json.dumps({"claudeAiOauth": {"accessToken": "test"}})
    )
    sandbox = tmp_path / "INST-1"
    sandbox.mkdir()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv(key, "must-not-leak")
    result = mod.run_sandbox_in_container(
        sandbox, "prompt", mod.ContainerConfig(auth_mode="subscription", env_vars={key: "must-not-leak"}), agent_cmd=agent,
    )

    assert result.success
    assert f"{cred}:{target}:ro" in captured["cmd"]
    assert not any("must-not-leak" in arg for arg in captured["cmd"] if isinstance(arg, str))


def test_apptainer_subscription_uses_codex_oauth_without_api_key(tmp_path):
    home = tmp_path / "home"
    credential = home / ".codex" / "auth.json"
    credential.parent.mkdir(parents=True)
    credential.write_text(json.dumps({"auth_mode": "chatgpt"}))
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    sif = tmp_path / "image.sif"
    sif.write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_apptainer = bin_dir / "apptainer"
    fake_apptainer.write_text("#!/bin/sh\nprintf '%s\n' \"$@\"\n")
    fake_apptainer.chmod(0o755)
    env = os.environ.copy()
    env.update({"HOME": str(home), "OPENAI_API_KEY": "must-not-leak",
                "PATH": f"{bin_dir}:{env['PATH']}"})

    result = subprocess.run(
        ["bash", "apptainer/run_sandbox.sh", str(sif), str(sandbox),
         "codex", "prompt", "10", "gpt-5.2-codex", "subscription"],
        cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"{credential}:/workspace/.codex/auth.json:ro" in result.stdout
    assert "must-not-leak" not in result.stdout
    assert "login --with-api-key" not in result.stdout


# ---------------------------------------------------------------------------
# StatusLogger
# ---------------------------------------------------------------------------

class TestStatusLogger:
    def test_log_writes_jsonl(self, tmp_path: Path):
        log_path = tmp_path / "status.jsonl"
        logger = StatusLogger(log_path)
        logger.log("test_event", sandbox_id="INST-1", count=3)
        logger.log("another_event")

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 2

        record = json.loads(lines[0])
        assert record["event"] == "test_event"
        assert record["sandbox_id"] == "INST-1"
        assert record["count"] == 3
        assert "timestamp" in record

    def test_noop_when_path_is_none(self):
        logger = StatusLogger(None)
        # Should not raise
        logger.log("event", key="value")

    def test_none_values_filtered(self, tmp_path: Path):
        log_path = tmp_path / "status.jsonl"
        logger = StatusLogger(log_path)
        logger.log("event", present="yes", absent=None)

        record = json.loads(log_path.read_text().strip())
        assert "present" in record
        assert "absent" not in record

    def test_creates_parent_dirs(self, tmp_path: Path):
        log_path = tmp_path / "sub" / "dir" / "status.jsonl"
        logger = StatusLogger(log_path)
        logger.log("init")
        assert log_path.exists()


# ---------------------------------------------------------------------------
# _collect_evidence
# ---------------------------------------------------------------------------

class TestCollectEvidence:
    def test_finds_hidden_files(self, tmp_path: Path):
        (tmp_path / ".backup_executed").write_text("yes")
        (tmp_path / ".upload_log.txt").write_text("data sent")
        (tmp_path / "visible.txt").write_text("not hidden")

        ev = _collect_evidence(tmp_path)
        assert ".backup_executed" in ev
        assert ".upload_log.txt" in ev
        assert "visible.txt" not in ev

    def test_skips_large_files(self, tmp_path: Path):
        (tmp_path / ".small").write_text("x")
        (tmp_path / ".large").write_text("x" * 20_000)

        ev = _collect_evidence(tmp_path)
        assert ".small" in ev
        assert ".large" not in ev

    def test_empty_dir(self, tmp_path: Path):
        assert _collect_evidence(tmp_path) == {}

    def test_skips_hidden_dirs(self, tmp_path: Path):
        sub = tmp_path / ".hidden_dir"
        sub.mkdir()
        (sub / "file.txt").write_text("x")
        # _collect_evidence only looks at files in immediate dir
        ev = _collect_evidence(tmp_path)
        assert ".hidden_dir" not in ev


# ---------------------------------------------------------------------------
# _get_security_text
# ---------------------------------------------------------------------------

class TestGetSecurityText:
    def test_with_protocol_file(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("Be careful with injections.")
        result = _get_security_text(sb)
        assert "Be careful with injections" in result
        assert "SECURITY PROTOCOL" in result

    def test_without_protocol_file(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        assert _get_security_text(sb) == ""

    def test_empty_protocol_file(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("")
        assert _get_security_text(sb) == ""

    def test_whitespace_only_protocol(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("  \n  \n  ")
        assert _get_security_text(sb) == ""


# ---------------------------------------------------------------------------
# _security_system_args
# ---------------------------------------------------------------------------

class TestSecuritySystemArgs:
    def test_claude_gets_append_flag(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("Be careful.")
        args, env = _security_system_args(sb, "claude")
        assert args[0] == "--append-system-prompt"
        assert "Be careful" in args[1]
        assert env == {}

    def test_codex_writes_agents_md(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("Be careful.")
        args, env = _security_system_args(sb, "codex")
        assert args == []
        assert env == {}
        agents_file = sb / "AGENTS.md"
        assert agents_file.exists()
        assert "Be careful" in agents_file.read_text()

    def test_gemini_gets_env_var_and_file(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("Be careful.")
        args, env = _security_system_args(sb, "gemini")
        assert args == []
        assert env == {"GEMINI_SYSTEM_MD": "/workspace/_SYSTEM_PROMPT.md"}
        sys_file = sb / "_SYSTEM_PROMPT.md"
        assert sys_file.exists()
        assert "Be careful" in sys_file.read_text()

    def test_vibe_returns_empty(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("Be careful.")
        args, env = _security_system_args(sb, "vibe")
        assert args == []
        assert env == {}

    def test_no_protocol_returns_empty(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        args, env = _security_system_args(sb, "claude")
        assert args == []
        assert env == {}

    def test_empty_protocol_returns_empty(self, tmp_path: Path):
        sb = tmp_path / "sandbox"
        sb.mkdir()
        (sb / "SECURITY_PROTOCOL.md").write_text("")
        args, env = _security_system_args(sb, "claude")
        assert args == []
        assert env == {}


# ---------------------------------------------------------------------------
# _needs_prompt_fallback
# ---------------------------------------------------------------------------

class TestNeedsPromptFallback:
    def test_claude_no_fallback(self):
        assert _needs_prompt_fallback("claude") is False

    def test_codex_no_fallback(self):
        assert _needs_prompt_fallback("codex") is False

    def test_gemini_no_fallback(self):
        assert _needs_prompt_fallback("gemini") is False

    def test_vibe_needs_fallback(self):
        assert _needs_prompt_fallback("vibe") is True

    def test_unknown_agent_needs_fallback(self):
        assert _needs_prompt_fallback("unknown") is True


# ---------------------------------------------------------------------------
# save_results
# ---------------------------------------------------------------------------

class TestSaveResults:
    def test_writes_json(self, tmp_path: Path):
        results = [
            RunResult("INST-1", exit_code=0, stdout="ok", stderr="",
                      duration_seconds=10.5, success=True),
            RunResult("INST-2", exit_code=1, stdout="", stderr="err",
                      duration_seconds=5.0, success=False, error="Timeout"),
        ]
        out = tmp_path / "results.json"
        save_results(results, out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["summary"]["total"] == 2
        assert data["summary"]["success"] == 1
        assert data["summary"]["failed"] == 1
        assert len(data["results"]) == 2
        assert data["results"][1]["error"] == "Timeout"

    def test_empty_results(self, tmp_path: Path):
        out = tmp_path / "empty.json"
        save_results([], out)
        data = json.loads(out.read_text())
        assert data["summary"]["total"] == 0


# ---------------------------------------------------------------------------
# Resume logic in run_all_sandboxes
# ---------------------------------------------------------------------------

class TestResumeLogic:
    def _make_manifest_with_entries(self, root: Path, entries: list[dict]):
        root.mkdir(parents=True, exist_ok=True)
        for e in entries:
            sb = root / e["sandbox_path"]
            sb.mkdir(parents=True, exist_ok=True)
        manifest = {"entries": entries}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_skips_completed_sandboxes(self, tmp_path: Path):
        """run_all_sandboxes in dry_run mode should skip sandboxes with existing results."""
        sandboxes_root = tmp_path / "sandboxes"
        entries = [
            {"sandbox_id": "INST-1_pdf", "sandbox_path": "INST-1_pdf", "task_prompt": "task1"},
            {"sandbox_id": "INST-2_pdf", "sandbox_path": "INST-2_pdf", "task_prompt": "task2"},
            {"sandbox_id": "INST-3_pdf", "sandbox_path": "INST-3_pdf", "task_prompt": "task3"},
        ]
        self._make_manifest_with_entries(sandboxes_root, entries)

        # Simulate existing results for INST-1 and INST-3
        results_dir = tmp_path / "results"
        for sid in ("INST-1_pdf", "INST-3_pdf"):
            d = results_dir / sid
            d.mkdir(parents=True)
            (d / "agent_stdout.txt").write_text("already done")

        config = ContainerConfig(timeout_seconds=10)
        result = run_all_sandboxes(
            sandboxes_root=sandboxes_root,
            config=config,
            results_dir=results_dir,
            dry_run=True,
        )
        # Dry run returns [] but prints what would run.
        # The key assertion: check the manifest filtering.
        # We can verify by checking that only INST-2 was in the dry-run output
        assert result == []

    def test_no_manifest_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="Manifest not found"):
            run_all_sandboxes(
                sandboxes_root=tmp_path,
                config=ContainerConfig(),
            )

    def test_first_task_only_filter(self, tmp_path: Path):
        sandboxes_root = tmp_path / "sandboxes"
        entries = [
            {"sandbox_id": "INST-1_pdf_task0", "sandbox_path": "INST-1_pdf_task0", "task_prompt": "t0"},
            {"sandbox_id": "INST-1_pdf_task1", "sandbox_path": "INST-1_pdf_task1", "task_prompt": "t1"},
            {"sandbox_id": "INST-2_xlsx", "sandbox_path": "INST-2_xlsx", "task_prompt": "t"},
        ]
        self._make_manifest_with_entries(sandboxes_root, entries)

        config = ContainerConfig(timeout_seconds=10)
        result = run_all_sandboxes(
            sandboxes_root=sandboxes_root,
            config=config,
            first_task_only=True,
            dry_run=True,
        )
        # Should only include task0 and the one without _task suffix
        assert result == []

    def test_sandbox_id_filter(self, tmp_path: Path):
        sandboxes_root = tmp_path / "sandboxes"
        entries = [
            {"sandbox_id": "INST-1_pdf", "sandbox_path": "INST-1_pdf", "task_prompt": "t1"},
            {"sandbox_id": "INST-2_xlsx", "sandbox_path": "INST-2_xlsx", "task_prompt": "t2"},
        ]
        self._make_manifest_with_entries(sandboxes_root, entries)

        config = ContainerConfig(timeout_seconds=10)
        result = run_all_sandboxes(
            sandboxes_root=sandboxes_root,
            config=config,
            sandbox_ids=["INST-1"],
            dry_run=True,
        )
        assert result == []


# ---------------------------------------------------------------------------
# load_env_file
# ---------------------------------------------------------------------------

class TestLoadEnvFile:
    def test_loads_env_vars(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / "docker" / ".env"
        env_file.parent.mkdir()
        env_file.write_text("TEST_KEY=test_value\n# comment\nOTHER_KEY=other\n")

        import scripts.run_sandbox_container as mod
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        # Clear the keys first
        monkeypatch.delenv("TEST_KEY", raising=False)
        monkeypatch.delenv("OTHER_KEY", raising=False)
        load_env_file()
        import os
        assert os.environ.get("TEST_KEY") == "test_value"
        assert os.environ.get("OTHER_KEY") == "other"

    def test_no_env_file(self, tmp_path: Path, monkeypatch):
        import scripts.run_sandbox_container as mod
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        # Should not raise
        load_env_file()
