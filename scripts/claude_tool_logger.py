#!/usr/bin/env python3
"""Install a Claude Code hook that records native tool calls in command history."""
from __future__ import annotations

import json
import sys
from pathlib import Path


HOOK_SOURCE = r'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

try:
    event = json.load(sys.stdin)
    tool_name = event.get("tool_name", "unknown")
    tool_input = event.get("tool_input", {})
    payload = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
    with Path("/workspace/.command_history").open("a", encoding="utf-8") as stream:
        stream.write(f"NATIVE_TOOL_CALL {tool_name} {payload}\n")
except Exception:
    # Telemetry must never interfere with the evaluated agent.
    pass
'''


def install_claude_tool_logger(workspace: Path) -> None:
    """Add a non-blocking PreToolUse logger to project-local Claude settings."""
    claude_dir = workspace / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_path = hooks_dir / "log_native_tool.py"
    hook_path.write_text(HOOK_SOURCE, encoding="utf-8")
    hook_path.chmod(0o755)

    settings_path = claude_dir / "settings.local.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (OSError, json.JSONDecodeError):
            raise ValueError(f"Invalid Claude settings JSON: {settings_path}")

    command = "/workspace/.claude/hooks/log_native_tool.py"
    handler = {"type": "command", "command": command}
    pre_tool_hooks = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    already_installed = any(
        hook.get("matcher") == "*" and handler in hook.get("hooks", [])
        for hook in pre_tool_hooks
        if isinstance(hook, dict)
    )
    if not already_installed:
        pre_tool_hooks.append({"matcher": "*", "hooks": [handler]})

    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: claude_tool_logger.py WORKSPACE")
    install_claude_tool_logger(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
