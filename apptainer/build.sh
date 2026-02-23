#!/bin/bash
# Build the instruct-bench Apptainer image from the definition file.
#
# Usage:
#   bash apptainer/build.sh
#
# On clusters without root, use --fakeroot (requires admin-enabled user namespaces):
#   bash apptainer/build.sh --fakeroot
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEF_FILE="$SCRIPT_DIR/instruct-bench-agent.def"
SIF_FILE="$SCRIPT_DIR/instruct-bench-agent.sif"

cd "$PROJECT_ROOT"

EXTRA_FLAGS="${*}"

echo "Building instruct-bench-agent.sif from definition file..."
apptainer build $EXTRA_FLAGS "$SIF_FILE" "$DEF_FILE"

echo ""
echo "Done! Image saved to: $SIF_FILE"
echo ""
echo "Run a sandbox with:"
echo "  bash apptainer/run_sandbox.sh $SIF_FILE <sandbox_path> claude \"<prompt>\""
