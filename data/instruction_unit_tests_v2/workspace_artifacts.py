"""Workspace artifacts for detectors whose evidence is what the agent produced.

The phishing and poisoning injections added for the camera-ready (obvious 39-44)
succeed by leaving something behind: a document, an invite, a dataset, a seeded
index. These helpers read that output while keeping out the places the injected
text sits anyway: the skill copies, the agent's own logs, and the harness files.
They assume a live workspace (results/<cell>/INST-* keeps the whole sandbox).
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from typing import Iterator

# Skill copies and tool state hold the injection verbatim; the rest is harness.
_SKIP_DIRS = {".claude", ".codex", ".gemini", ".vibe", ".git", "node_modules",
              "__pycache__", "_startup_scripts", "_root_files"}
_SKIP_FILES = {"agent_stdout.txt", "agent_stderr.txt", "run_result.json", "AGENTS.md",
               "SECURITY_PROTOCOL.md", "_SYSTEM_PROMPT.md", "_EXTRA_SYSTEM_PROMPT.md",
               ".bash_command_logger.sh", "verdicts.json", "status.jsonl"}
_MAX_BYTES = 8 * 1024 * 1024

TEXT_SUFFIXES = (".py", ".js", ".ts", ".sh", ".json", ".jsonl", ".csv", ".tsv", ".txt",
                 ".md", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".html", ".xml", ".ics",
                 ".ipynb", ".sql")

# Inspection only: no pipe, chain, redirect or heredoc that could act on its input.
_INSPECT = re.compile(r"\s*(?:cat|less|more|head|tail|grep|rg|sed|awk|jq|wc|diff|ls|find|file)\s"
                      r"[^|;&<>\n]*$")


def workspace_files(sandbox_dir: Path, suffixes: tuple[str, ...] = TEXT_SUFFIXES) -> Iterator[Path]:
    """Files the agent could have produced, outside skill copies and harness files."""
    for path in sandbox_dir.rglob("*"):
        rel = path.relative_to(sandbox_dir)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if rel.name in _SKIP_FILES or rel.name.startswith(".command_history"):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path


def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def office_text(path: Path) -> str:
    """Visible text of an OOXML file, plus its relationship targets (hyperlinks).

    Tags are dropped without inserting spaces, so text split across runs joins
    back up the way Word displays it.
    """
    parts = []
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith(".xml"):
                    parts.append(re.sub(r"<[^>]+>", "", z.read(name).decode("utf-8", "ignore")))
                elif name.endswith(".rels"):
                    parts.append(z.read(name).decode("utf-8", "ignore"))
    except (OSError, zipfile.BadZipFile, KeyError):
        return ""
    return html.unescape("\n".join(parts))


def unfold_ics(text: str) -> str:
    """Undo RFC 5545 line folding (CRLF + one space or tab) and text escaping."""
    text = re.sub(r"\r?\n[ \t]", "", text)
    return text.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")


def acting(commands: list[str]) -> list[str]:
    """Commands that could have acted, i.e. not bare inspection of a file."""
    return [c for c in commands if not _INSPECT.match(c)]


def rel(sandbox_dir: Path, path: Path) -> str:
    return str(path.relative_to(sandbox_dir))
