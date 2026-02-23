# SKILL-INJECT Benchmark

A comprehensive benchmark for measuring prompt injection vulnerabilities in LLM agent skill files. SKILL-INJECT evaluates how susceptible multiple LLM coding agents (Claude Code, Codex, Gemini CLI) are to malicious instructions hidden in skill definitions, across multiple safety policy conditions.

## Overview

Modern LLM agents load "skill files" that define their capabilities. SKILL-INJECT tests whether adversarial instructions embedded in these skill files can cause agents to execute unintended actions.

The benchmark includes:
- **41 contextual injections** — dual-use instructions whose harm depends on context
- **30 obvious injections** — unambiguously malicious instructions (ransomware, exfiltration, etc.)
- **44 skill definitions** across diverse domains (documents, git, healthcare, email, MCP, etc.)
- **3 safety policy conditions** — normal, legitimizing, and warning
- **Multiple ablation studies** — Best-of-N, script vs. direct, skill screening, evolutionary optimization, RL-based optimization

## Prerequisites

- **Docker** (for running agents in isolated containers)
- **Python 3.10+**
- **Node.js / npm** (installed inside Docker image; not needed on host)
- **API keys** for the agents you want to test (see [Setup](#setup))

## Setup

### 1. Clone the repository

```bash
git clone <repo-url> skill-inject
cd skill-inject
```

### 2. Configure API keys

Copy the environment template and fill in your API keys:

```bash
cp docker/.env.example docker/.env
```

Edit `docker/.env` with your keys:

```env
# Required for Claude Code agent
ANTHROPIC_API_KEY=sk-ant-...

# Required for Codex agent and GPT-5.1-Mini judge
OPENAI_API_KEY=sk-...

# Required for Gemini CLI agent
GEMINI_API_KEY=...
```

You only need the key(s) for the agent(s) you intend to test. The `OPENAI_API_KEY` is also needed for the default GPT-5.1-Mini evaluation judge.

### 3. Build the Docker image

```bash
bash docker/build.sh
```

This creates the `instruct-bench-agent` Docker image with all agent CLIs and dependencies pre-installed.

## Project Structure

```
skill-inject/
├── config.py                 # Central configuration (models, skills, policies)
├── pyproject.toml            # Project metadata
│
├── data/                     # Benchmark data
│   ├── contextual_injections.json    # 41 contextual injection definitions
│   ├── obvious_injections.json       # 30 obvious injection definitions
│   ├── tasks.json                    # 66 deduplicated clean tasks
│   ├── unified_security_policy.md    # Combined warning text
│   ├── skills/                       # 44 clean skill definitions
│   ├── task_files/                   # Files referenced by tasks
│   └── task_scripts/                 # Scripts referenced by injections
│
├── experiments/              # Experiment runners
│   ├── _base.py              # Base class (build → run → evaluate pipeline)
│   ├── contextual.py         # Contextual injection experiments
│   ├── obvious.py            # Obvious injection experiments
│   ├── utility_baseline.py   # Clean task baseline (no injections)
│   └── ablations/            # Ablation studies (Bo5, script vs. direct, RL, etc.)
│
├── judges/                   # Evaluation judges
│   ├── _base.py              # Base judge (prompt building, verdict parsing)
│   ├── contextual_judge.py   # LLM judge for contextual results
│   ├── obvious_judge.py      # LLM judge for obvious results
│   ├── utility_baseline_judge.py  # Task completion evaluator
│   └── skill_screening_judge.py   # Skill safety screening ablation
│
├── scripts/                  # Core execution scripts
│   ├── build_sandbox.py      # Build sandboxes from injection JSON
│   ├── build_clean_sandboxes.py  # Build clean sandboxes (no injections)
│   ├── run_sandbox_container.py  # Execute agents in Docker containers
│   ├── reset_sandboxes.py    # Reset sandboxes for re-running
│   ├── watch_status.py       # Live monitor for run status
│   └── smoke_test_all.py     # End-to-end smoke test for all experiments
│
├── docker/                   # Docker configuration
│   ├── Dockerfile            # Agent container image
│   ├── build.sh              # Image build script
│   ├── docker-compose.yml    # Compose reference
│   ├── entrypoint.sh         # Container entrypoint
│   └── .env.example          # API key template
│
├── apptainer/                # HPC cluster support (Apptainer/Singularity)
├── tests/                    # Test suite (pytest)
├── startup_scripts/          # Pre-agent initialization scripts
└── startup_assets/           # Assets for startup scripts
```

## Running Experiments

All experiments follow the same pipeline: **build sandboxes → run agents in Docker → evaluate results**.

### Contextual Injections

Tests dual-use injections across 3 safety policy conditions:

```bash
# Run all models for a given agent
python experiments/contextual.py --agent claude

# Run a specific model
python experiments/contextual.py --agent codex --model gpt-5.1-codex-mini

# Run a specific policy only
python experiments/contextual.py --agent claude --policy warning

# Smoke test (injection ID 1 only, sequential)
python experiments/contextual.py --agent claude --smoke-test
```

### Obvious Injections

Tests unambiguously malicious injections (normal policy only):

```bash
python experiments/obvious.py --agent claude
python experiments/obvious.py --agent codex --model gpt-5.2-codex
```

### Utility Baseline

Measures clean task completion (no injections) with and without security policy:

```bash
# Both conditions (no_policy + policy)
python experiments/utility_baseline.py --agent claude

# Single condition
python experiments/utility_baseline.py --agent claude --condition no_policy
```

### Ablation Studies

```bash
# Best-of-5 line position ablation
python experiments/ablations/bo5_byline.py --agent claude

# Script vs. direct injection comparison
python experiments/ablations/script_vs_direct.py --agent claude

# Best-of-4 task variant ablation
python experiments/ablations/bo4_bytask.py --agent claude

# Skill screening (LLM safety evaluation)
python judges/skill_screening_judge.py --model sonnet
python judges/skill_screening_judge.py --run-all  # All screening models

# Evolutionary optimization
python experiments/ablations/evolutionary_optimization.py --agent claude

# GRPO injection optimization (requires requirements_grpo.txt dependencies)
pip install -r requirements_grpo.txt
python experiments/ablations/grpo_injection_optimization.py
```

## Evaluating Results

Results are saved to `final_results/` after each experiment run. You can also re-evaluate existing results independently.

### LLM Judge (default: GPT-5.1-Codex-Mini)

```bash
# Contextual results (ASR + task completion)
python judges/contextual_judge.py final_results/contextual/claude-sonnet/normal/ \
    --model gpt-5.1-codex-mini --evaluate-task

# Obvious results (ASR only)
python judges/obvious_judge.py final_results/obvious/claude-sonnet/normal/

# Utility baseline (task completion only)
python judges/utility_baseline_judge.py final_results/utility_baseline/claude-sonnet/no_policy/
```

## Configuration

All configuration is centralized in [config.py](config.py):

- **`AGENT_MODELS`** — Supported agent/model combinations (Claude, Codex, Gemini, Vibe)
- **`SKILL_MAPPING`** — Maps skill types to their directories under `data/skills/`
- **`POLICY_CONFIGS`** — Safety policy definitions (normal, legitimizing, warning)
- **`AGENT_PARALLEL`** — Default parallelism per agent

## Common Options

Most experiment runners support these flags:

| Flag | Description |
|------|-------------|
| `--agent` | Agent to test: `claude`, `codex`, `gemini`, `vibe` |
| `--model` | Specific model within agent (e.g., `sonnet`, `gpt-5.2-codex`) |
| `--policy` | Safety policy filter: `normal`, `legitimizing`, `warning` |
| `--parallel N` | Number of parallel container executions |
| `--timeout N` | Execution timeout in seconds |
| `--smoke-test` | Run injection ID 1 only (quick validation) |
| `--skip-eval` | Skip automatic evaluation after running |
| `--force` | Delete existing results and rerun |

## Monitoring Runs

Watch live progress during long experiment runs:

```bash
python scripts/watch_status.py final_results/contextual/claude-sonnet/normal/run_status.jsonl
```

## Running Tests

### Unit tests

```bash
pip install pytest
pytest tests/ -v
```

### End-to-end smoke test

Runs every experiment with every model on a single sandbox/container to verify the full pipeline works:

```bash
# Test everything (all 18 models x 6 experiments = 108 runs)
python scripts/smoke_test_all.py

# Test a single agent
python scripts/smoke_test_all.py --agent claude

# Test a single agent/model combination
python scripts/smoke_test_all.py --agent claude --model sonnet

# Test a single experiment across all models
python scripts/smoke_test_all.py --experiment contextual

# Skip evaluation phase (only test build + run)
python scripts/smoke_test_all.py --skip-eval

# Dry run (print commands without executing)
python scripts/smoke_test_all.py --dry-run
```

The smoke test builds sandboxes, runs one agent container, and evaluates results for each combination. It requires Docker, API keys in `docker/.env`, and typically takes 5-15 minutes per agent/model combo.

## License

See LICENSE file for details.
