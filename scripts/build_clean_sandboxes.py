#!/usr/bin/env python3
"""Build clean sandboxes from tasks.json with no injections.

Each sandbox contains:
- Clean skill file (no injections)
- Task files
- Task scripts
- Optional SECURITY_PROTOCOL.md with unified security policy
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# Add parent to path for config import
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    PROJECT_ROOT,
    get_skill_path,
)

# Agent skill layout
AGENT_SKILL_LAYOUT = {
    "claude": {"skills_dir": ".claude/skills"},
    "codex": {"skills_dir": ".codex/skills"},
    "gemini": {"skills_dir": ".gemini/skills"},
}


def build_clean_sandboxes(
    agent: str,
    tasks_file: Path,
    sandboxes_root: Path,
    security_policy_file: Path | None = None,
    clobber: bool = False,
    task_id_filter: int | None = None,
) -> None:
    """Build clean sandboxes for each task in tasks.json.

    Args:
        agent: Agent name (claude, codex, gemini)
        tasks_file: Path to tasks.json
        sandboxes_root: Root directory for sandboxes
        security_policy_file: Optional path to security policy (e.g. unified_security_policy.md)
        clobber: Delete existing sandboxes before building
        task_id_filter: If set, only build this task ID
    """
    if clobber and sandboxes_root.exists():
        print(f"[clobber] Removing {sandboxes_root}")
        shutil.rmtree(sandboxes_root)

    sandboxes_root.mkdir(parents=True, exist_ok=True)

    # Load tasks
    with tasks_file.open() as f:
        tasks = json.load(f)

    if task_id_filter:
        tasks = [t for t in tasks if t["id"] == task_id_filter]
        if not tasks:
            raise ValueError(f"No task with id={task_id_filter}")

    # Load security policy text if provided
    security_text = ""
    if security_policy_file and security_policy_file.exists():
        security_text = security_policy_file.read_text(encoding="utf-8").strip()

    # Build manifest entries
    manifest_entries = []

    for task in tasks:
        task_id = task["id"]
        skill_name = task["skill"]
        prompt = task["prompt"]
        task_files = task.get("task_files", {})
        task_scripts = task.get("task_scripts", {})

        # Create sandbox directory
        sandbox_id = f"TASK-{task_id}_{skill_name}"
        sandbox_dir = sandboxes_root / sandbox_id
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        # Copy clean skill directory to agent-specific location
        skill_rel = get_skill_path(skill_name)
        skill_src = PROJECT_ROOT / "data" / "skills" / skill_rel
        if not skill_src.exists():
            print(f"[warn] Skill not found: {skill_src}")
            continue

        agent_layout = AGENT_SKILL_LAYOUT[agent]
        skill_dest_dir = sandbox_dir / agent_layout["skills_dir"]
        skill_dest_dir.mkdir(parents=True, exist_ok=True)

        skill_dest = skill_dest_dir / skill_src.name
        if skill_src.is_dir():
            shutil.copytree(skill_src, skill_dest, dirs_exist_ok=True)
        else:
            shutil.copy2(skill_src, skill_dest)

        # Copy task files
        for filename, rel_path in task_files.items():
            src = PROJECT_ROOT / "data" / rel_path
            if not src.exists():
                print(f"[warn] Task file not found: {src}")
                continue
            dest = sandbox_dir / filename
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)

        # Copy task scripts to scripts/ subdirectory
        if task_scripts:
            scripts_dir = sandbox_dir / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            for script_name, rel_path in task_scripts.items():
                src = PROJECT_ROOT / "data" / rel_path
                if not src.exists():
                    print(f"[warn] Task script not found: {src}")
                    continue
                dest = scripts_dir / script_name
                shutil.copy2(src, dest)

        # Write security protocol if provided
        if security_text:
            protocol_file = sandbox_dir / "SECURITY_PROTOCOL.md"
            protocol_file.write_text(security_text, encoding="utf-8")

        # Add to manifest
        manifest_entries.append({
            "sandbox_id": sandbox_id,
            "sandbox_path": sandbox_id,
            "task_id": task_id,
            "skill": skill_name,
            "task_prompt": prompt,  # Changed from "prompt" to "task_prompt" to match runner
            "num_task_files": len(task_files),
            "num_task_scripts": len(task_scripts),
            "has_security_protocol": bool(security_text),
        })

        print(f"[done] {sandbox_id} (skill: {skill_name}, "
              f"{len(task_files)} files, {len(task_scripts)} scripts)")

    # Write manifest
    manifest = {
        "agent": agent,
        "tasks_file": str(tasks_file),
        "security_policy_file": str(security_policy_file) if security_policy_file else None,
        "num_sandboxes": len(manifest_entries),
        "entries": manifest_entries,
    }

    manifest_file = sandboxes_root / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"[ok] Created {len(manifest_entries)} sandboxes, "
          f"manifest: {manifest_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Build clean sandboxes from tasks.json (no injections)"
    )
    parser.add_argument("--agent", required=True,
                        choices=["claude", "codex", "gemini"])
    parser.add_argument("--tasks-file", type=Path, required=True,
                        help="Path to tasks.json")
    parser.add_argument("--sandboxes-root", type=Path, required=True,
                        help="Root directory for sandboxes")
    parser.add_argument("--security-policy", type=Path,
                        help="Optional security policy file (e.g. unified_security_policy.md)")
    parser.add_argument("--clobber", action="store_true",
                        help="Delete existing sandboxes before building")
    parser.add_argument("--task-id", type=int,
                        help="Only build this task ID (for testing)")

    args = parser.parse_args()

    build_clean_sandboxes(
        agent=args.agent,
        tasks_file=args.tasks_file,
        sandboxes_root=args.sandboxes_root,
        security_policy_file=args.security_policy,
        clobber=args.clobber,
        task_id_filter=args.task_id,
    )


if __name__ == "__main__":
    main()
