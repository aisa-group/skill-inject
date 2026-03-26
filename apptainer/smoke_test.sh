#!/bin/bash
# Smoke test for the instruct-bench-agent Apptainer container.
# Verifies all expected tools are present and functional.
set -e

SIF="/lustre/home/dschmotz/skill-inject/apptainer/instruct-bench-agent.sif"
PASS=0
FAIL=0

run_check() {
    local label="$1"
    shift
    if apptainer exec "$SIF" "$@" &>/dev/null; then
        echo "[PASS] $label"
        PASS=$((PASS + 1))
    else
        echo "[FAIL] $label"
        FAIL=$((FAIL + 1))
    fi
}

run_output() {
    local label="$1"
    shift
    local out
    out=$(apptainer exec "$SIF" "$@" 2>&1) && echo "[PASS] $label: $out" && PASS=$((PASS + 1)) \
        || { echo "[FAIL] $label"; FAIL=$((FAIL + 1)); }
}

echo "=== Apptainer Container Smoke Test ==="
echo "SIF: $SIF"
echo "Size: $(du -sh "$SIF" | cut -f1)"
echo ""

run_output "python version"    python3 --version
run_output "node version"      node --version
run_output "npm version"       npm --version
run_output "git version"       git --version
run_output "xvfb present"      which Xvfb
run_output "xclip present"     which xclip
run_output "zip present"       which zip
run_output "unzip present"     which unzip

echo ""
echo "--- Python packages ---"
run_check "python-pptx"        python3 -c "import pptx"
run_check "python-docx"        python3 -c "import docx"
run_check "openpyxl"           python3 -c "import openpyxl"
run_check "PyPDF2"             python3 -c "import PyPDF2"
run_check "requests"           python3 -c "import requests"
run_check "flask"              python3 -c "import flask"
run_check "icalendar"          python3 -c "import icalendar"
run_check "mcp"                python3 -c "import mcp"

echo ""
echo "--- Agent CLIs ---"
run_check "claude CLI"         which claude
run_check "codex CLI"          which codex
run_check "gemini CLI"         which gemini
run_output "claude version"    claude --version

echo ""
echo "--- npm packages ---"
run_check "pptxgenjs"          node -e "require('pptxgenjs')"
run_check "typescript"         which tsc
run_check "ts-node"            which ts-node

echo ""
echo "==========================="
echo "Results: $PASS passed, $FAIL failed"
echo "==========================="
[ "$FAIL" -eq 0 ] && echo "All checks passed!" && exit 0 || exit 1
