#!/usr/bin/env python3
"""Standalone LLM agent using OpenRouter API with tool use.

Implements a simple agent loop: prompt -> LLM response -> tool execution -> repeat.
Designed to replicate the behavior of agent CLIs (claude, codex, gemini) for
running in sandbox directories.

No external dependencies — uses only the Python standard library (urllib).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command in the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating parent directories if necessary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
]


def _log_command(command: str) -> None:
    """Append a bash command to .command_history in the cwd."""
    try:
        with open(".command_history", "a", encoding="utf-8") as f:
            f.write(command + "\n")
    except Exception:
        pass


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool call and return the result as a string."""
    if name == "bash":
        command = arguments.get("command", "")
        _log_command(command)
        try:
            r = subprocess.run(
                command, shell=True,
                capture_output=True, text=True, timeout=120,
            )
            output = ""
            if r.stdout:
                output += r.stdout
            if r.stderr:
                output += ("\n" if output else "") + r.stderr
            if r.returncode != 0:
                output += f"\n[exit code: {r.returncode}]"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "[command timed out after 120s]"
        except Exception as e:
            return f"[error: {e}]"

    elif name == "read_file":
        try:
            with open(arguments["path"], "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content) > 100_000:
                content = content[:100_000] + "\n[truncated at 100k chars]"
            return content
        except Exception as e:
            return f"[error reading file: {e}]"

    elif name == "write_file":
        try:
            path = arguments["path"]
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(arguments["content"])
            return f"[wrote {len(arguments['content'])} bytes to {path}]"
        except Exception as e:
            return f"[error writing file: {e}]"

    return f"[unknown tool: {name}]"


# ---------------------------------------------------------------------------
# OpenRouter API (raw urllib, no dependencies)
# ---------------------------------------------------------------------------

def _call_openrouter(
    api_key: str, model: str, messages: list[dict], tools: list[dict],
) -> dict:
    """Make a chat completion request to OpenRouter. Returns the parsed JSON."""
    body = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "max_tokens": 16384,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_BASE_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/instruct-bench",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(
            f"OpenRouter API error {e.code}: {error_body}"
        ) from e


def run_agent(
    model: str,
    prompt: str,
    system_prompt: str | None = None,
    max_turns: int = 25,
) -> None:
    """Run the agent loop."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("[error] OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for turn in range(max_turns):
        try:
            resp = _call_openrouter(api_key, model, messages, TOOLS)
        except Exception as e:
            print(f"\n[API error on turn {turn + 1}: {e}]", file=sys.stderr)
            break

        choice = resp.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls") or []

        # Print any text content
        if content:
            print(content, flush=True)

        # If no tool calls, we're done
        if not tool_calls:
            break

        # Add assistant message to history
        assistant_msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            tc_id = tc.get("id", "")
            try:
                arguments = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            print(f"\n[tool: {name}] {json.dumps(arguments, ensure_ascii=False)}", flush=True)
            result = execute_tool(name, arguments)
            # Truncate very long results to avoid context overflow
            if len(result) > 50_000:
                result = result[:50_000] + "\n[truncated at 50k chars]"
            print(result, flush=True)

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })
    else:
        print(f"\n[agent reached max turns ({max_turns})]", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenRouter LLM agent with tool use"
    )
    parser.add_argument("prompt", help="The task prompt")
    parser.add_argument("--model", required=True, help="OpenRouter model ID")
    parser.add_argument("--system-prompt", default=None)
    parser.add_argument("--max-turns", type=int, default=25)
    args = parser.parse_args()

    run_agent(args.model, args.prompt, args.system_prompt, args.max_turns)


if __name__ == "__main__":
    main()
