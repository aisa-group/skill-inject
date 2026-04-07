#!/bin/bash
# Run obvious injection error bars (remaining) experiment on the cluster using Apptainer.
#
# Usage (via condor):
#   condor_submit_bid 20 -a "AGENT=claude" -a "MODEL=haiku" apptainer/run_obvious_eb_remaining.sub
#   condor_submit_bid 20 -a "AGENT=claude" -a "MODEL=claude-sonnet-4-6" apptainer/run_obvious_eb_remaining.sub
#
# Environment variables:
#   AGENT       - agent name: claude, codex, gemini, vibe (required)
#   MODEL       - model name (required)
#   TIMEOUT     - per-sandbox timeout in seconds (default: 500)
set -euo pipefail

PROJECT_ROOT="/lustre/home/dschmotz/skill-inject"
cd "$PROJECT_ROOT"

[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

AGENT="${AGENT:?Set AGENT to claude, codex, gemini, or vibe}"
MODEL="${MODEL:?Set MODEL}"
TIMEOUT="${TIMEOUT:-500}"
RERUN="${RERUN:-0}"
ONLY_RUNS="${ONLY_RUNS:-}"

SCRIPT="experiments/ablations/obvious_injection_error_bars_remaining.py"

echo "=== Obvious Injection Error Bars (Remaining) ==="
echo "Agent: $AGENT | Model: $MODEL | Timeout: $TIMEOUT"
echo "Script: $SCRIPT"
echo "Started: $(date)"
echo ""

EXTRA_FLAGS=()
[ "$RERUN" = "1" ] && EXTRA_FLAGS+=(--rerun)
[ -n "$ONLY_RUNS" ] && EXTRA_FLAGS+=(--only-runs ${ONLY_RUNS//,/ })

python3 "$SCRIPT" \
    --agent "$AGENT" \
    --model "$MODEL" \
    --timeout "$TIMEOUT" \
    --runtime apptainer \
    "${EXTRA_FLAGS[@]}"

echo ""
echo "Finished: $(date)"
