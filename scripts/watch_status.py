#!/usr/bin/env python3
"""Live terminal monitor for JSONL status logs.

Tails the run_status.jsonl file produced by run_sandbox_container.py,
tracks active/completed/failed counts, and prints a status summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def format_duration(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def stream_events(path: Path) -> None:
    """Tail the JSONL file and print live status."""
    active: dict[str, float] = {}
    completed = 0
    failed = 0
    total = 0
    t0 = time.time()

    print(f"Watching: {path}")
    print("Waiting for events...\n")

    pos = 0
    while True:
        try:
            with path.open("r", encoding="utf-8") as f:
                f.seek(pos)
                new_lines = f.readlines()
                pos = f.tell()
        except FileNotFoundError:
            time.sleep(1)
            continue

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = ev.get("event", "")
            sid = ev.get("sandbox_id", "")

            if event == "run_start":
                total = ev.get("total", 0)
                print(f"Run started: {total} sandboxes, parallel={ev.get('parallel', '?')}")

            elif event == "sandbox_start":
                active[sid] = time.time()

            elif event == "sandbox_complete":
                active.pop(sid, None)
                if ev.get("success"):
                    completed += 1
                else:
                    failed += 1
                dur = ev.get("duration", ev.get("duration_seconds", 0))
                tag = "OK" if ev.get("success") else "FAIL"
                print(f"  [{tag}] {sid} ({format_duration(dur)})")

            elif event == "run_complete":
                elapsed = time.time() - t0
                print(f"\nRun complete in {format_duration(elapsed)}")
                print(f"  OK: {ev.get('success', completed)}")
                print(f"  FAIL: {ev.get('failed', failed)}")
                return

        # Status line
        if total:
            done = completed + failed
            elapsed = format_duration(time.time() - t0)
            sys.stdout.write(
                f"\r  [{done}/{total}] active={len(active)} ok={completed} "
                f"fail={failed} elapsed={elapsed}   "
            )
            sys.stdout.flush()

        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch sandbox run status")
    parser.add_argument("status_log", type=Path, help="Path to run_status.jsonl")
    args = parser.parse_args()
    try:
        stream_events(args.status_log)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
