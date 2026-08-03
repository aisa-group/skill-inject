"""Resolve per-task facts from the injection definitions.

Tests used to hardcode the files they expected a sandbox to contain.  That is
how ``test_instruction_4`` came to look for ``Q4_financial_report.xlsx``, which
no task ever ships — the xlsx tasks ship ``numbers.xlsx``.  Each task ships
exactly *one* file, so a hardcoded list of three is wrong for every sandbox.

Reading the task files from the injection definition keeps the tests in step
with the data they are scoring.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent

_SOURCES = {
    "contextual": "contextual_injections.json",
    "obvious": "obvious_injections.json",
}


@lru_cache(maxsize=4)
def _load(category: str) -> dict[int, dict]:
    path = _DATA_DIR / _SOURCES[category]
    try:
        return {x["id"]: x for x in json.loads(path.read_text(encoding="utf-8"))}
    except Exception:
        return {}


def task_index_of(sandbox_name: str) -> int | None:
    """``INST-4_docx_legitimizing_task5`` -> 5."""
    m = re.search(r"task(\d+)$", sandbox_name)
    return int(m.group(1)) if m else None


def task_files_for(injection_id: int, sandbox_name: str,
                   category: str = "contextual") -> tuple[str, ...]:
    """Files the sandbox was seeded with, for this injection and task.

    Falls back to the union across tasks matching the skill named in the
    sandbox directory, then to the union across all tasks.
    """
    inj = _load(category).get(injection_id)
    if not inj:
        return ()
    tasks = inj.get("tasks") or []

    idx = task_index_of(sandbox_name)
    if idx is not None and idx < len(tasks):
        return tuple((tasks[idx].get("task_files") or {}).keys())

    parts = sandbox_name.split("_")
    skill = parts[1] if len(parts) > 1 else ""
    matching = [t for t in tasks if t.get("skill") == skill]
    pool = matching or tasks
    out: list[str] = []
    for t in pool:
        out.extend((t.get("task_files") or {}).keys())
    return tuple(dict.fromkeys(out))
