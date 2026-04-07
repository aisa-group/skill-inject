#!/bin/bash
# Run a bo5 ablation experiment on the cluster using Apptainer.
#
# Usage (via condor):
#   condor_submit_bid 20 -a "EXPERIMENT=bytask" -a "AGENT=codex" -a "MODEL=gpt-5.2-codex" apptainer/run_bo5.sub
#   condor_submit_bid 20 -a "EXPERIMENT=byline" -a "AGENT=claude" -a "MODEL=sonnet" apptainer/run_bo5.sub
#
# Environment variables:
#   EXPERIMENT  - which bo5 script to run: bytask, byline (required)
#   AGENT       - agent name: claude, codex, gemini (required)
#   MODEL       - model name (required)
#   TIMEOUT     - per-sandbox timeout in seconds (default: 500)
set -euo pipefail

PROJECT_ROOT="/lustre/home/dschmotz/skill-inject"
cd "$PROJECT_ROOT"

EXPERIMENT="${EXPERIMENT:?Set EXPERIMENT to bytask or byline}"
AGENT="${AGENT:?Set AGENT to claude, codex, or gemini}"
MODEL="${MODEL:?Set MODEL}"
TIMEOUT="${TIMEOUT:-500}"

case "$EXPERIMENT" in
    bytask)
        SCRIPT="experiments/ablations/bo5_bytask.py"
        ;;
    byline)
        SCRIPT="experiments/ablations/bo5_byline.py"
        ;;
    *)
        echo "Unknown experiment: $EXPERIMENT (use bytask or byline)" >&2
        exit 1
        ;;
esac

echo "=== Bo5 $EXPERIMENT ==="
echo "Agent: $AGENT | Model: $MODEL | Timeout: $TIMEOUT"
echo "Script: $SCRIPT"
echo "Started: $(date)"
echo ""

python3 "$SCRIPT" \
    --agent "$AGENT" \
    --model "$MODEL" \
    --timeout "$TIMEOUT" \
    --runtime apptainer

echo ""
echo "Finished: $(date)"
