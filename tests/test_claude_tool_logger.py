from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.claude_tool_logger import install_claude_tool_logger


def test_installs_hook_and_preserves_existing_settings(tmp_path: Path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    settings_path = claude / "settings.local.json"
    settings_path.write_text(json.dumps({"permissions": {"allow": ["Read"]}}))

    install_claude_tool_logger(tmp_path)
    install_claude_tool_logger(tmp_path)

    settings = json.loads(settings_path.read_text())
    assert settings["permissions"] == {"allow": ["Read"]}
    hooks = settings["hooks"]["PreToolUse"]
    assert len(hooks) == 1
    assert hooks[0]["matcher"] == "*"
    assert hooks[0]["hooks"][0]["command"] == "/workspace/.claude/hooks/log_native_tool.py"


def test_hook_appends_compact_native_tool_call(tmp_path: Path):
    install_claude_tool_logger(tmp_path)
    hook = tmp_path / ".claude" / "hooks" / "log_native_tool.py"
    source = hook.read_text().replace("/workspace", str(tmp_path))
    local_hook = tmp_path / "hook.py"
    local_hook.write_text(source)

    event = {"tool_name": "Write", "tool_input": {"file_path": "/workspace/a.txt", "content": "a\nb"}}
    result = subprocess.run(
        ["python3", str(local_hook)], input=json.dumps(event), text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert (tmp_path / ".command_history").read_text() == (
        'NATIVE_TOOL_CALL Write {"file_path":"/workspace/a.txt","content":"a\\nb"}\n'
    )
