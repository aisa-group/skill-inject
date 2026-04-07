#!/usr/bin/env python3
"""Build sandboxes from a unified injection JSON file.

Reads injection definitions (each containing injection instructions + associated
tasks), creates one sandbox directory per injection-task pair. Each sandbox
contains the skill with the injection embedded, task files, and a manifest.

Sandbox naming: INST-{id}_{skill}[_{suffix}]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    DATA_DIR,
    DILUTION_SKILL_POOL,
    PROJECT_ROOT,
    SKILL_ROOT,
    STARTUP_SCRIPTS_DIR,
    get_skill_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_id_list(items: list[str] | None) -> list[str]:
    """Parse comma-separated ID lists into flat list of strings."""
    result: list[str] = []
    for chunk in items or []:
        for part in chunk.split(","):
            part = part.strip()
            if part:
                result.append(part)
    return result


def load_injections_file(path: Path) -> list[dict]:
    """Load and validate the unified injections JSON file."""
    if not path.exists():
        sys.exit(f"[error] Injections file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            sys.exit(f"[error] Failed to parse {path}: {exc}")
    if not isinstance(data, list):
        sys.exit(f"[error] Expected a JSON array at root of {path}")
    return data


def resolve_target_file(skill_dir: Path, preferred: str) -> Path:
    """Find the target file to inject into within a skill directory."""
    candidate = skill_dir / preferred
    if candidate.exists():
        return candidate
    matches = list(skill_dir.rglob(preferred))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"[error] Could not find '{preferred}' under {skill_dir}")
    sys.exit(f"[error] Multiple '{preferred}' files under {skill_dir}")


# ---------------------------------------------------------------------------
# Injection functions
# ---------------------------------------------------------------------------

def inject_at_line(file_path: Path, instruction_text: str, line_number: int) -> None:
    """Insert instruction text at a specific line number in a file."""
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if line_number < 1 or line_number > len(lines) + 1:
        sys.exit(
            f"[error] Line {line_number} out of range "
            f"(file has {len(lines)} lines): {file_path}"
        )
    block: list[str] = []
    for raw in instruction_text.strip("\n").splitlines():
        block.append(f"{raw.strip()}\n" if raw.strip() else "\n")
    pos = line_number - 1
    file_path.write_text("".join(lines[:pos] + block + lines[pos:]), encoding="utf-8")


def inject_into_description(file_path: Path, instruction_text: str) -> None:
    """Append instruction to the YAML frontmatter description field."""
    content = file_path.read_text(encoding="utf-8")
    yaml_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE)
    if not yaml_match:
        sys.exit(f"[error] No YAML frontmatter found in {file_path}")

    yaml_block = yaml_match.group(1)
    yaml_end = yaml_match.end()
    clean = instruction_text.strip()

    # Try multi-line block scalar (> or |)
    block_re = re.compile(
        r"^description:\s*([>|])\s*\n((?:[ \t]+.+\n?)+)", re.MULTILINE
    )
    bm = block_re.search(yaml_block)
    if bm:
        lines = bm.group(2).rstrip("\n").split("\n")
        lines[-1] = lines[-1].rstrip() + " " + clean
        new_block = "\n".join(lines) + "\n"
        new_yaml = (
            yaml_block[: bm.start()]
            + f"description: {bm.group(1)}\n{new_block}"
            + yaml_block[bm.end() :]
        )
    else:
        # Single-line description
        desc_re = re.compile(r'^description:\s*["\']?(.*?)["\']?\s*$', re.MULTILINE)
        dm = desc_re.search(yaml_block)
        if not dm:
            sys.exit(f"[error] No 'description' in YAML frontmatter of {file_path}")
        orig = dm.group(1).strip().strip("\"'")
        escaped = clean.replace('"', '\\"')
        new_yaml = desc_re.sub(f'description: "{orig} {escaped}"', yaml_block)

    file_path.write_text(f"---\n{new_yaml}\n---\n{content[yaml_end:]}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Safety protocol
# ---------------------------------------------------------------------------

def copy_safety_protocol(
    sandbox_dir: Path,
    skill_layout: str,
    context_variant: str | None = None,
    context_text: str | None = None,
    as_skill: bool = False,
) -> None:
    """Create a security protocol file (or skill) in the sandbox."""
    if as_skill:
        layout_map = {
            "claude": ".claude", "codex": ".codex",
            "gemini": ".gemini", "vibe": ".vibe",
        }
        prefix = layout_map.get(skill_layout, "")
        skill_dir = sandbox_dir / prefix / "skills" / "security" if prefix else sandbox_dir / "security"
        skill_dir.mkdir(parents=True, exist_ok=True)
        header = (
            "---\n"
            "name: security\n"
            "description: Security and safety protocols for agent operations.\n"
            "---\n\n"
        )
        body = (header + context_text + "\n") if context_text else header
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    else:
        body = (context_text + "\n") if context_text else ""
        (sandbox_dir / "SECURITY_PROTOCOL.md").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Sandbox builder
# ---------------------------------------------------------------------------

def build_sandbox(
    injection: dict,
    task_info: dict,
    sandbox_root: Path,
    skill_root_dir: Path,
    target_file_name: str,
    skill_layout: str = "claude",
    safety_protocol_mode: int = 0,
    safety_context_variant: str | None = None,
    safety_context_text: str | None = None,
    sandbox_suffix: str | None = None,
    security_as_skill: bool = False,
    dry_run: bool = False,
    enable_description_injection: bool = False,
    dilution_skill_paths: list[str] | None = None,
) -> dict:
    """Build a single sandbox for an injection + task pair. Returns manifest entry."""
    injection_id = injection.get("id")
    skill_type = task_info.get("skill", "")
    task_prompt = task_info.get("prompt", "")
    line_num = task_info.get("line_num")
    injection_prefix = task_info.get("injection_prefix", "")

    instructions = injection.get("instructions", {})
    line_injection = instructions.get("line_injection", "")
    if line_injection and injection_prefix:
        line_injection = injection_prefix + line_injection

    if not skill_type:
        print(f"[warn] Injection {injection_id} has no skill, skipping")
        return {}

    skill_rel = get_skill_path(skill_type)
    skill_name = Path(skill_rel).name

    sandbox_id = f"INST-{injection_id}_{skill_name}"
    if sandbox_suffix:
        sandbox_id += f"_{sandbox_suffix}"
    sandbox_dir = sandbox_root / sandbox_id

    desc_injection = instructions.get("description_injection", "")

    if dry_run:
        print(f"[plan] {sandbox_id} (skill: {skill_type})")
        return {
            "sandbox_id": sandbox_id,
            "injection_id": injection_id,
            "skill": skill_type,
            "sandbox_path": sandbox_id,
            "task_prompt": task_prompt,
            "safety_protocol_variant": safety_context_variant,
        }

    # Create sandbox dir
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    # Copy skill into agent-specific layout
    skill_src = skill_root_dir / skill_rel
    if not skill_src.exists():
        sys.exit(f"[error] Skill path not found: {skill_src}")

    layout_prefix = {"codex": ".codex", "gemini": ".gemini", "vibe": ".vibe"}.get(
        skill_layout, ".claude"
    )
    skill_dst = sandbox_dir / layout_prefix / "skills" / skill_name
    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_src, skill_dst, dirs_exist_ok=True)

    # Gemini settings.json
    if skill_layout == "gemini":
        gemini_dir = sandbox_dir / ".gemini"
        gemini_dir.mkdir(parents=True, exist_ok=True)
        (gemini_dir / "settings.json").write_text(
            json.dumps({"experimental": {"skills": True}}, indent=2) + "\n",
            encoding="utf-8",
        )

    target_file = resolve_target_file(skill_dst, target_file_name)

    # Apply injections
    if desc_injection and enable_description_injection:
        inject_into_description(target_file, desc_injection)
    if line_injection and line_num:
        inject_at_line(target_file, line_injection, line_num)

    # Copy dilution skills (benign, no injection) alongside the target skill
    copied_dilution: list[str] = []
    for dil_rel in (dilution_skill_paths or []):
        dil_src = skill_root_dir / dil_rel
        if not dil_src.exists():
            print(f"[warn] Dilution skill not found: {dil_src}")
            continue
        dil_name = Path(dil_rel).name
        dil_dst = sandbox_dir / layout_prefix / "skills" / dil_name
        dil_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dil_src, dil_dst, dirs_exist_ok=True)
        copied_dilution.append(dil_name)

    # Copy task files to sandbox root
    copied_task_files: list[str] = []
    for _key, fpath in task_info.get("task_files", {}).items():
        src = DATA_DIR / fpath
        if not src.exists():
            continue
        dst = sandbox_dir / src.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied_task_files.append(src.name)

    # Copy root_files (mounted above /workspace in container)
    copied_root_files: list[str] = []
    root_files_list = injection.get("root_files", [])
    if root_files_list:
        root_dir = sandbox_dir / "_root_files"
        root_dir.mkdir(parents=True, exist_ok=True)
        for rf in root_files_list:
            src = DATA_DIR / rf
            if not src.exists():
                print(f"[warn] root_file not found: {src}")
                continue
            dst = root_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            copied_root_files.append(src.name)

    # Copy task scripts into skill's scripts/ folder
    copied_task_scripts: list[str] = []
    for script_name, script_path in injection.get("task_scripts", {}).items():
        src = DATA_DIR / script_path
        if not src.exists():
            continue
        scripts_dir = skill_dst / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        dst = scripts_dir / script_name
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        copied_task_scripts.append(script_name)

    # Copy startup scripts
    copied_startup: list[str] = []
    for entry in injection.get("startup_scripts", []):
        if isinstance(entry, dict):
            name, src = entry.get("name"), Path(entry.get("path", ""))
        else:
            name, src = str(entry), STARTUP_SCRIPTS_DIR / str(entry)
        if not name or not src.exists():
            continue
        startup_dir = sandbox_dir / "_startup_scripts"
        startup_dir.mkdir(parents=True, exist_ok=True)
        dst = startup_dir / name
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        copied_startup.append(name)

    # Safety protocol
    if safety_protocol_mode >= 1:
        copy_safety_protocol(
            sandbox_dir, skill_layout,
            context_variant=safety_context_variant,
            context_text=safety_context_text,
            as_skill=security_as_skill,
        )

    print(
        f"[done] {sandbox_id} "
        f"(skill: {skill_type}, {len(copied_task_files)} files, "
        f"{len(copied_task_scripts)} scripts, {len(copied_dilution)} dilution skills)"
    )

    return {
        "sandbox_id": sandbox_id,
        "injection_id": injection_id,
        "skill": skill_type,
        "skill_path": skill_rel,
        "sandbox_path": sandbox_id,
        "target_file": str(target_file.relative_to(sandbox_dir)),
        "task_files": copied_task_files,
        "task_scripts": copied_task_scripts,
        "root_files": copied_root_files,
        "startup_scripts": copied_startup,
        "dilution_skills": copied_dilution,
        "task_prompt": task_prompt,
        "safety_protocol_variant": safety_context_variant,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build sandboxes from injection JSON")
    parser.add_argument("--injections-file", type=Path, default=Path("obvious_injections.json"))
    parser.add_argument("--injection-id", action="append", default=[])
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--sandboxes-root", type=Path, default=None)
    parser.add_argument("--skill-root", type=Path, default=SKILL_ROOT)
    parser.add_argument("--target-file", default="SKILL.md")
    parser.add_argument("--clobber", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agent", choices=["claude", "codex", "gemini", "vibe"], default="claude")
    parser.add_argument("--safety-protocol", type=int, choices=[0, 1, 2, 3], default=0)
    parser.add_argument("--security-skill", action="store_true")
    parser.add_argument("--description-injection", action="store_true")
    parser.add_argument("--first-task-only", action="store_true",
                        help="Only build the first task per injection (for smoke tests)")
    parser.add_argument("--dilution-count", type=int, default=0,
                        help="Number of benign distractor skills to add to each sandbox "
                             "(drawn from DILUTION_SKILL_POOL, excludes the task skill)")
    parser.add_argument("--dilution-seed", type=int, default=42,
                        help="Random seed for dilution skill selection (default: 42)")
    args = parser.parse_args()

    # Derive sandboxes root from injections filename if not provided
    if args.sandboxes_root is None:
        category = Path(args.injections_file).stem.replace("_injections", "")
        args.sandboxes_root = Path("sandboxes") / category / args.agent

    injections = load_injections_file(args.injections_file)

    # Filter by ID
    id_filter = parse_id_list(args.injection_id)
    if id_filter:
        injections = [i for i in injections if str(i.get("id")) in id_filter]

    skill_filter = set(parse_id_list(args.skill))

    if not injections:
        print("[warn] No injections to process")
        return

    # Archive or clobber
    if not args.dry_run and args.sandboxes_root.exists() and not args.clobber:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive = Path("sandbox_archives") / f"sandbox_runs_{ts}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        print(f"[archive] {args.sandboxes_root} -> {archive}")
        shutil.copytree(args.sandboxes_root, archive)
        shutil.rmtree(args.sandboxes_root)

    if not args.dry_run:
        args.sandboxes_root.mkdir(parents=True, exist_ok=True)

    # Determine skill layout
    layout_map = {"codex": "codex", "gemini": "gemini", "vibe": "vibe"}
    skill_layout = layout_map.get(args.agent, "claude")

    # Build safety-protocol variant list
    def make_variants(ctx: dict) -> list[tuple]:
        if args.safety_protocol == 3:
            return [
                ("legitimizing", "legitimizing", ctx.get("legitimizing"), 2),
                ("warning", "warning", ctx.get("warning"), 2),
                ("no_protocol", None, None, 0),
            ]
        if args.safety_protocol == 2:
            return [
                ("legitimizing", "legitimizing", ctx.get("legitimizing"), 2),
                ("warning", "warning", ctx.get("warning"), 2),
            ]
        if args.safety_protocol == 1:
            return [(None, None, None, 1)]
        return [(None, None, None, 0)]

    manifest_entries: list[dict] = []
    rng = random.Random(args.dilution_seed)

    for inj in injections:
        ctx = inj.get("context", {})
        tasks = inj.get("tasks", [])
        if not tasks:
            old = inj.get("task")
            tasks = [old] if old else []
        if not tasks:
            print(f"[warn] Injection {inj.get('id')} has no tasks, skipping")
            continue

        variants = make_variants(ctx)

        for tidx, task in enumerate(tasks):
            if skill_filter and task.get("skill", "") not in skill_filter:
                continue

            # Resolve dilution skills: exclude the task's own skill name
            dilution_paths: list[str] = []
            if args.dilution_count > 0:
                task_skill_name = Path(get_skill_path(task.get("skill", ""))).name
                pool = [s for s in DILUTION_SKILL_POOL if Path(s).name != task_skill_name]
                n = min(args.dilution_count, len(pool))
                dilution_paths = rng.sample(pool, n)

            for vsuffix, cvar, ctext, smode in variants:
                full_suffix = vsuffix
                if len(tasks) > 1:
                    ts = f"task{tidx}"
                    full_suffix = f"{vsuffix}_{ts}" if vsuffix else ts

                meta = build_sandbox(
                    injection=inj,
                    task_info=task,
                    sandbox_root=args.sandboxes_root,
                    skill_root_dir=args.skill_root,
                    target_file_name=args.target_file,
                    skill_layout=skill_layout,
                    safety_protocol_mode=smode,
                    safety_context_variant=cvar,
                    safety_context_text=ctext,
                    sandbox_suffix=full_suffix,
                    security_as_skill=args.security_skill,
                    dry_run=args.dry_run,
                    enable_description_injection=args.description_injection,
                    dilution_skill_paths=dilution_paths,
                )
                if meta:
                    meta["timestamp_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    meta["injection_context"] = ctx
                    meta["injection_type"] = inj.get("type", "")
                    meta["judge_prompt"] = inj.get("judge_prompt", "")
                    manifest_entries.append(meta)
            if args.first_task_only:
                break

    # Write manifest
    if args.dry_run:
        print(f"[dry-run] Planned {len(manifest_entries)} sandboxes")
    else:
        manifest_path = args.sandboxes_root / "manifest.json"
        manifest_path.write_text(
            json.dumps({"entries": manifest_entries}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"[ok] Created {len(manifest_entries)} sandboxes, manifest: {manifest_path}")


if __name__ == "__main__":
    main()
