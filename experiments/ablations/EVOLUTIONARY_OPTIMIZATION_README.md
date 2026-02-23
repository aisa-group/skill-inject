# Evolutionary Optimization for Prompt Injections Ablation

This ablation implements a evolutionary algorithm-inspired approach to adaptively improve prompt injection effectiveness through iterative optimization.

## Overview

Based on the methodology from [arxiv.org/pdf/2510.04885](https://arxiv.org/pdf/2510.04885), this ablation treats injection optimization as a sequential decision problem where:

- **State**: Current injection text
- **Action**: LLM-generated mutation/variant
- **Reward**: Attack Success Rate (ASR) from evaluation
- **Policy**: LLM-based mutation strategy that learns from previous iterations

## Algorithm

```
1. Initialize with base injections from dataset
2. For N iterations:
   a. Generate K variants using LLM mutation agent
   b. Run agent experiments with each variant
   c. Evaluate ASR (reward signal)
   d. Select best-performing variants
   e. Update mutation strategy based on feedback
3. Track improvement trajectory
```

## Key Components

### RLMutationAgent

An LLM-powered mutation agent that generates injection variants. The agent:
- Analyzes feedback from previous iterations
- Identifies successful patterns
- Generates diverse variants using linguistic/psychological strategies:
  - Authority/legitimacy framing
  - Contextualization and justification
  - Indirect/euphemistic language
  - Technical jargon
  - Urgency or time pressure
  - Social proof appeals

### Feedback Loop

After each iteration:
1. **ASR Computation**: Measure success rate across all variants
2. **Variant Selection**: Choose top-k performing variants
3. **History Tracking**: Maintain per-injection history of attempts and outcomes
4. **Strategy Adaptation**: Feed results back to mutation agent for next iteration

### Hyperparameters

- `--generations`: Number of Evolutionary optimization rounds (default: 5)
- `--variants-per-generation`: Variants to test per iteration (default: 3)
- `--top-k`: Number of top variants to keep (default: 1)

## Usage

### Basic Usage

```bash
# Run with default settings (5 iterations, 3 variants/iter)
python3 experiments/ablations/evolutionary_optimization.py --agent claude --model sonnet

# Custom hyperparameters
python3 experiments/ablations/evolutionary_optimization.py \
    --agent claude --model sonnet \
    --generations 10 \
    --variants-per-generation 5 \
    --top-k 2

# Smoke test (2 iterations, 2 variants, injection ID 1 only)
python3 experiments/ablations/evolutionary_optimization.py \
    --agent claude --model sonnet \
    --smoke-test

# Specific injection IDs only
python3 experiments/ablations/evolutionary_optimization.py \
    --agent claude --model sonnet \
    --injection-id 1 --injection-id 5 --injection-id 12
```

### Evaluation and Visualization

```bash
# Generate trajectory plots
python3 scripts/plots/plot_rl_trajectory.py --all

# Individual plot types
python3 scripts/plots/plot_rl_trajectory.py --combined    # All models on one plot
python3 scripts/plots/plot_rl_trajectory.py --grid        # Separate subplots
python3 scripts/plots/plot_rl_trajectory.py --summary     # Initial vs final ASR bars
```

## Output Structure

```
final_results/ablations/evolutionary_optimization/
└── {agent-model}/                          # e.g., claude-sonnet/
    ├── rl_optimization_results.json        # Main results file
    ├── injections_iter0.json               # Variant definitions per iteration
    ├── injections_iter1.json
    ├── ...
    ├── {agent}_iter0/                      # Sandbox directories per iteration
    ├── {agent}_iter1/
    ├── ...
    ├── results_iter0/                      # Evaluation results per iteration
    │   ├── INST-1_0_TASK-0/
    │   ├── INST-1_1_TASK-0/
    │   ├── ...
    │   └── evaluation_llmjudge_haiku.json
    ├── results_iter1/
    └── ...
```

### Results JSON Schema

```json
{
  "agent": "claude",
  "model": "sonnet",
  "n_iterations": 5,
  "variants_per_iteration": 3,
  "trajectory": [
    {
      "iteration": 0,
      "asr": 0.45,
      "eval_data": {...},
      "best_variants": {
        "1": "best variant text for injection 1",
        "2": "best variant text for injection 2"
      }
    },
    ...
  ],
  "final_best_injections": {
    "1": "final optimized text for injection 1",
    "2": "final optimized text for injection 2"
  },
  "history_per_injection": {
    "1": [
      {
        "iteration": 0,
        "injection": "variant text",
        "asr": 0.45,
        "successful": true
      },
      ...
    ]
  }
}
```

## Expected Results

### Hypothesis

RL-based adaptive optimization should demonstrate:
1. **Progressive improvement**: ASR increases over iterations
2. **Agent vulnerability**: More capable models may be more susceptible to optimized injections
3. **Injection heterogeneity**: Some injections improve more than others
4. **Diminishing returns**: Improvement may plateau after several iterations

### Metrics

- **Initial ASR**: Success rate with base injection (iteration 0)
- **Final ASR**: Success rate with optimized injection (last iteration)
- **Improvement**: Δ ASR from initial to final
- **Convergence**: Iteration at which ASR plateaus

## Comparison to Other Ablations

| Ablation | Approach | Key Insight |
|----------|----------|-------------|
| **Evolutionary Optimization** (this) | Iterative optimization with LLM-guided mutations | How much can injections improve with adaptive refinement? |
| Bo5 Byline | Position variation within skill file | Does line number affect ASR? |
| Script vs Direct | Delivery mechanism (file vs text) | Are indirect injections more effective? |
| Skill Screening | Detection by LLM scanner | Can automated screening catch malicious skills? |

## Paper Integration

This ablation provides evidence for:
- **Section 5.3 (Ablations)**: Add subsection on adaptive optimization
- **Section 6 (Discussion)**: Discuss implications of adaptive attacks
- **Section 7 (Defenses)**: Motivate need for robust defenses against optimized injections

Suggested paper text:

> **Adaptive Optimization**: We evaluate whether iterative refinement using an LLM-based mutation agent can improve injection effectiveness. Starting from our base injections, we run N=5 optimization rounds where each iteration generates K=3 variants, evaluates their ASR, and uses the best performers to seed the next round. Results show [X% average improvement / plateauing after Y iterations / heterogeneous effects across models], indicating that [adversaries with adaptive capabilities / defense mechanisms must account for evolving threats / etc.].

## Dependencies

- `anthropic` Python package (for mutation agent)
- All standard SKILL-INJECT dependencies
- Docker (for sandboxed execution)

## Testing

```bash
# Run RL ablation tests
pytest tests/test_evolutionary_optimization.py -v

# Run smoke test to validate end-to-end
python3 experiments/ablations/evolutionary_optimization.py --agent claude --model sonnet --smoke-test
```

## Troubleshooting

### LLM Mutation Agent Failures

If the mutation agent fails to generate valid variants:
- Check `ANTHROPIC_API_KEY` is set
- Review error messages in output
- Fallback: returns base injection (experiments continue)

### Slow Execution

Evolutionary optimization is computationally expensive:
- Each iteration runs full experiment + evaluation
- Expected runtime: ~1-2 hours per model for 5 iterations with 3 variants
- Use `--smoke-test` for quick validation
- Reduce `--generations` or `--variants-per-generation` for faster runs

### No Improvement Observed

If ASR doesn't improve:
- Check if base injections already have high ASR (ceiling effect)
- Increase `--generations` to allow more exploration
- Increase `--variants-per-generation` for more diversity
- Inspect `history_per_injection` in results JSON to diagnose

## Future Extensions

1. **Multi-objective optimization**: Balance ASR and stealth (lower detection rate)
2. **Cross-model transfer**: Train on one model, test on another
3. **Human-in-the-loop**: Expert feedback to guide mutations
4. **Ensemble mutations**: Combine multiple mutation strategies
5. **Gradient-based optimization**: Use embedding-space gradients instead of LLM mutations

## References

- Main paper: [arxiv.org/pdf/2510.04885](https://arxiv.org/pdf/2510.04885)
- SKILL-INJECT paper: (this work)
- Related work: GCG, AutoDAN, PAIR, TAP
