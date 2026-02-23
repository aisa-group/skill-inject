#!/bin/bash
# Run all ablation experiments.
# Usage: ./run_all_ablations.sh --agent claude [--model sonnet] [--smoke-test]
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "=== Bo5 byline ablation ==="
python3 "$PROJECT_ROOT/experiments/ablations/bo5_byline.py" "$@"

echo ""
echo "=== Script vs Direct ablation ==="
python3 "$PROJECT_ROOT/experiments/ablations/script_vs_direct.py" "$@"

echo ""
echo "=== Skill screening ablation ==="
python3 "$PROJECT_ROOT/judges/skill_screening_judge.py" --model sonnet

echo ""
echo "=== Evolutionary Optimization ablation ==="
python3 "$PROJECT_ROOT/experiments/ablations/evolutionary_optimization.py" "$@"

echo ""
echo "All ablations complete."
