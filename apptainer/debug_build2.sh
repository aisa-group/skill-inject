#!/bin/bash
set -x

# Set temp dir to lustre for space
export TMPDIR="/lustre/home/dschmotz/skill-inject/apptainer/tmp_debug"
mkdir -p "$TMPDIR"
export APPTAINER_TMPDIR="$TMPDIR"
export APPTAINER_CACHEDIR="$TMPDIR/cache"

echo "=== Testing minimal def build ==="
cat > /tmp/minimal.def << 'DEFEOF'
Bootstrap: docker
From: python:3.11-slim

%post
    echo "Hello from post"
    python3 --version
DEFEOF

apptainer build --debug /tmp/minimal.sif /tmp/minimal.def 2>&1 | tail -30
echo "=== Exit code: $? ==="
