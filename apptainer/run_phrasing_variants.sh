#!/bin/bash
# Run phrasing variants ablation on the cluster using Apptainer.
#
# Usage (via condor):
#   condor_submit_bid 20 -a "AGENT=claude" -a "MODEL=sonnet" apptainer/run_phrasing_variants.sub
#
# Environment variables:
#   AGENT    - agent name: claude, codex, gemini, vibe (required)
#   MODEL    - model name (required)
#   TIMEOUT  - per-sandbox timeout in seconds (default: 300)
set -euo pipefail

PROJECT_ROOT="/lustre/home/dschmotz/skill-inject"
cd "$PROJECT_ROOT"

[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

AGENT="${AGENT:?Set AGENT to claude, codex, gemini, or vibe}"
MODEL="${MODEL:?Set MODEL}"
TIMEOUT="${TIMEOUT:-300}"
RESULTS_DIR="${RESULTS_DIR:-}"

echo "=== Phrasing Variants Ablation ==="
echo "Agent: $AGENT | Model: $MODEL | Timeout: $TIMEOUT"
[ -n "$RESULTS_DIR" ] && echo "Results dir: $RESULTS_DIR"
echo "Started: $(date)"
echo ""

EXTRA_FLAGS=()
[ -n "$RESULTS_DIR" ] && EXTRA_FLAGS+=(--results-dir "$RESULTS_DIR")

python3 experiments/ablations/phrasing_variants.py \
    --agent "$AGENT" \
    --model "$MODEL" \
    --timeout "$TIMEOUT" \
    --runtime apptainer \
    "${EXTRA_FLAGS[@]}"

echo ""
echo "Finished: $(date)"
