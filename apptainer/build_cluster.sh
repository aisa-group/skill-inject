#!/bin/bash
# Build the Apptainer image on an HTCondor compute node.
# Builds to /tmp first (avoids lustre compatibility issues), then copies to lustre.
set -e

PROJECT_DIR="/lustre/home/dschmotz/skill-inject"
DEF_FILE="$PROJECT_DIR/apptainer/instruct-bench-agent.def"
SIF_FILE="$PROJECT_DIR/apptainer/instruct-bench-agent.sif"
TMP_SIF="/tmp/instruct-bench-agent.sif"

# Point apptainer temp/cache at /tmp (request_disk ensures enough space)
export APPTAINER_TMPDIR="/tmp/apptainer_tmp"
export APPTAINER_CACHEDIR="/tmp/apptainer_cache"
mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"

echo "=== Build started: $(date) ==="
echo "Node: $(hostname)"
echo "Apptainer: $(apptainer --version)"
echo "DEF: $DEF_FILE"
echo "SIF (final): $SIF_FILE"
echo ""

echo "[1/2] Building SIF to /tmp ..."
apptainer build "$TMP_SIF" "$DEF_FILE"

echo ""
echo "[2/2] Copying SIF to lustre ..."
cp "$TMP_SIF" "$SIF_FILE"
rm -f "$TMP_SIF"

echo ""
echo "=== Build complete: $(date) ==="
echo "Image size: $(du -sh "$SIF_FILE" | cut -f1)"
