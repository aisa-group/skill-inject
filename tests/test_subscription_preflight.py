import json
import os
from pathlib import Path
import subprocess

from scripts.subscription_preflight import MARKER, subscription_env, verdict


def test_apptainer_subscription_blocks_all_provider_keys_and_dotenv(tmp_path):
    project = Path(__file__).resolve().parents[1]
    launcher = tmp_path / "apptainer/run_sandbox.sh"
    launcher.parent.mkdir()
    launcher.write_text((project / "apptainer/run_sandbox.sh").read_text())
    (launcher.parent / ".env").write_text(
        "OPENAI_API_KEY=DOTENV_MUST_NOT_LEAK\n"
        "ANTHROPIC_API_KEY=DOTENV_MUST_NOT_LEAK\n"
        "OPENAI_BASE_URL=https://DOTENV_MUST_NOT_LEAK\n"
    )
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}))
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake_apptainer = binaries / "apptainer"
    fake_apptainer.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" '
        '"${APPTAINERENV_OPENAI_API_KEY-}" '
        '"${SINGULARITYENV_ANTHROPIC_API_KEY-}"\n'
    )
    fake_apptainer.chmod(0o755)
    env = dict(os.environ, HOME=str(home), PATH=f"{binaries}:{os.environ['PATH']}")
    for name in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "MISTRAL_API_KEY", "HF_TOKEN",
                 "APPTAINERENV_OPENAI_API_KEY", "SINGULARITYENV_ANTHROPIC_API_KEY"]:
        env[name] = "ENV_MUST_NOT_LEAK"
    result = subprocess.run(
        ["bash", str(launcher), str(tmp_path / "fake.sif"), str(sandbox),
         "codex", "prompt", "10", "gpt-5.2", "subscription"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "MUST_NOT_LEAK" not in result.stdout + result.stderr
    assert "--cleanenv" in result.stdout
    assert "login --with-api-key" not in result.stdout


def test_preflight_environment_excludes_keys_routes_and_container_overrides():
    source = {
        "HOME": "/home/example", "PATH": "/bin", "https_proxy": "http://proxy",
        "OPENAI_API_KEY": "secret", "ANTHROPIC_API_KEY": "secret",
        "GEMINI_API_KEY": "secret", "OPENAI_BASE_URL": "https://other",
        "APPTAINERENV_OPENAI_API_KEY": "secret",
        "SINGULARITYENV_ANTHROPIC_API_KEY": "secret",
        "CLAUDE_CODE_USE_BEDROCK": "1", "BASH_ENV": "/tmp/inject.sh",
    }
    result = subscription_env(source)
    assert result == {
        "HOME": "/home/example", "PATH": "/bin", "https_proxy": "http://proxy",
        "no_proxy": "localhost,127.0.0.1,::1,localnet",
        "NO_PROXY": "localhost,127.0.0.1,::1,localnet",
    }


def test_codex_error_with_zero_exit_is_not_a_success():
    output = json.dumps({"type": "error", "message": "Model not supported"})
    assert verdict("codex", 0, output, "") == "model_unavailable"


def test_codex_requires_completed_turn_and_real_assistant_response():
    message = json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": MARKER}})
    assert verdict("codex", 0, message, "") == "unexpected_response"
    complete = json.dumps({"type": "turn.completed"})
    assert verdict("codex", 0, message + "\n" + complete, "") == "passed"
    assert verdict("codex", 0, complete, MARKER) == "unexpected_response"


def test_claude_requires_exact_success_marker():
    assert verdict("claude", 0, MARKER + "\n", "") == "passed"
    assert verdict("claude", 1, MARKER, "") == "failed"
    assert verdict("claude", 0, "Authentication failed", "401") == "authentication_failed"
    assert verdict("claude", 124, "", "") == "timed_out"
def test_cancelled_campaign_stage_never_invokes_a_model(tmp_path, monkeypatch):
    import json
    import sys
    from scripts import subscription_preflight as preflight

    (tmp_path / "model_selection.json").write_text(json.dumps({
        "active_models": ["claude-sonnet-4-5"],
        "cancelled_models": ["claude-haiku-4-5-20251001", "claude-opus-4-5-20251101"],
    }))
    output = tmp_path / "preflight"
    monkeypatch.setenv("_CONDOR_SCRATCH_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["subscription_preflight.py", "--provider", "claude",
                                    "--model", "claude-haiku-4-5-20251001",
                                    "--output", str(output), "--execute"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Cancelled stage attempted a model call")
    monkeypatch.setattr(preflight.subprocess, "run", forbidden)
    assert preflight.main() == 78
    assert json.loads((output / "cancelled_stage.json").read_text())["model_calls"] == 0

