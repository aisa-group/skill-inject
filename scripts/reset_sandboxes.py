#!/usr/bin/env python3
"""Remove execution artifacts from sandbox directories.

Deletes agent_stdout.txt, agent_stderr.txt, execution_result.json, and
run_status.jsonl while preserving the base sandbox setup (skills, task files,
manifest). Allows re-running without rebuilding.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ARTIFACTS = {
    "agent_stdout.txt",
    "agent_stderr.txt",
    "execution_result.json",
    "run_status.jsonl",
}


def reset_sandbox(sandbox_dir: Path, dry_run: bool = False) -> int:
    """Remove artifacts from a single sandbox. Returns count of files removed."""
    removed = 0
    for name in ARTIFACTS:
        f = sandbox_dir / name
        if f.exists():
            if dry_run:
                print(f"  [dry-run] would remove {f}")
            else:
                f.unlink()
            removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset sandboxes for re-running")
    parser.add_argument("sandboxes_root", type=Path, help="Root directory containing INST-* sandboxes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.sandboxes_root.exists():
        sys.exit(f"[error] Not found: {args.sandboxes_root}")

    dirs = sorted(
        d for d in args.sandboxes_root.iterdir()
        if d.is_dir() and d.name.startswith("INST-")
    )
    if not dirs:
        print(f"No INST-* directories in {args.sandboxes_root}")
        return

    total = 0
    for d in dirs:
        n = reset_sandbox(d, args.dry_run)
        if n:
            print(f"  {d.name}: {n} artifact(s) {'would be ' if args.dry_run else ''}removed")
            total += n

    print(f"\n{'Would remove' if args.dry_run else 'Removed'} {total} artifact(s) from {len(dirs)} sandboxes")


if __name__ == "__main__":
    main()
