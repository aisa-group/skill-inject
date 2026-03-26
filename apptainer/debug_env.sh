#!/bin/bash
SIF="/lustre/home/dschmotz/skill-inject/apptainer/instruct-bench-agent.sif"
SANDBOX="/lustre/home/dschmotz/skill-inject/apptainer/smoke_sandbox/TASK-1_pptx"

# Simulate what run_sandbox.sh does
SCRIPT_DIR="/lustre/home/dschmotz/skill-inject/apptainer"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_FLAGS=()
if [ -f "$ENV_FILE" ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        key="$(echo "$key" | xargs)"
        value="$(echo "$value" | xargs)"
        [ -n "$value" ] && ENV_FLAGS+=(--env "${key}=${value}")
    done < "$ENV_FILE"
fi

echo "ENV_FLAGS count: ${#ENV_FLAGS[@]}"
echo "Testing key inside container..."
apptainer exec --containall --writable-tmpfs --home /workspace \
    --bind "${SANDBOX}:/workspace" \
    "${ENV_FLAGS[@]}" \
    "$SIF" bash -c 'echo "OPENAI_API_KEY len=${#OPENAI_API_KEY}"; echo "first20=${OPENAI_API_KEY:0:20}"'
