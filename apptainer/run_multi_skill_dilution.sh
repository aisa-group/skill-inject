#!/bin/bash
# Run multi-skill dilution ablation on the cluster using Apptainer.
#
# Usage (via condor):
#   condor_submit_bid 20 -a "AGENT=claude" -a "MODEL=sonnet" apptainer/run_multi_skill_dilution.sub
#
# Environment variables:
#   AGENT       - agent name: claude, codex, gemini, vibe (required)
#   MODEL       - model name (required)
#   TIMEOUT     - per-sandbox timeout in seconds (default: 500)
#   RATIOS      - space-separated dilution ratios to test (default: "0 1 3 5 10")
set -euo pipefail

PROJECT_ROOT="/lustre/home/dschmotz/skill-inject"
cd "$PROJECT_ROOT"

[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

AGENT="${AGENT:?Set AGENT to claude, codex, gemini, or vibe}"
MODEL="${MODEL:?Set MODEL}"
TIMEOUT="${TIMEOUT:-500}"
RATIOS="${RATIOS:-0 1 3 5 10}"

SCRIPT="experiments/ablations/multi_skill_dilution.py"

echo "=== Multi-Skill Dilution Ablation ==="
echo "Agent: $AGENT | Model: $MODEL | Timeout: $TIMEOUT"
echo "Ratios: $RATIOS"
echo "Script: $SCRIPT"
echo "Started: $(date)"
echo ""

python3 "$SCRIPT" \
    --agent "$AGENT" \
    --model "$MODEL" \
    --timeout "$TIMEOUT" \
    --ratios $RATIOS \
    --runtime apptainer

echo ""
echo "Finished: $(date)"
