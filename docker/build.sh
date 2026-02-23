#!/bin/bash
# Quick build script for instruct-bench Docker image
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "Building instruct-bench-agent image..."
docker build -t instruct-bench-agent -f docker/Dockerfile docker/

echo "Done! Run sandboxes with:"
echo "  python scripts/run_sandbox_container.py run --sandboxes-root sandbox_runs"
