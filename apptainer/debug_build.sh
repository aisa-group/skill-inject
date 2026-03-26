#!/bin/bash
set -x
echo "=== Environment ==="
env | sort
echo "=== Apptainer version ==="
apptainer --version
echo "=== Testing docker pull ==="
apptainer pull /tmp/test_python.sif docker://python:3.11-slim 2>&1
echo "=== Exit code: $? ==="
