#!/bin/bash
set -x

echo "=== Test 1: build from lustre def to /tmp ==="
apptainer build /tmp/test1.sif /lustre/home/dschmotz/skill-inject/apptainer/instruct-bench-agent.def
echo "Test1 exit: $?"

echo "=== Test 2: build from /tmp def to /tmp ==="
cp /lustre/home/dschmotz/skill-inject/apptainer/instruct-bench-agent.def /tmp/test.def
apptainer build /tmp/test2.sif /tmp/test.def
echo "Test2 exit: $?"

echo "=== Test 3: build with --userns ==="
apptainer build --userns /tmp/test3.sif /tmp/test.def
echo "Test3 exit: $?"
