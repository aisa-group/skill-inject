# True RL Policy Gradient Training for Injection Optimization

This ablation implements **actual reinforcement learning** with policy gradients, as described in the paper (https://arxiv.org/pdf/2510.04885).

## Key Difference from Evolutionary Optimization

| Aspect | Evolutionary Optimization | RL Policy Gradient (This) |
|--------|---------------------------|---------------------------|
| **Approach** | Black-box, LLM-as-optimizer | White-box, gradient-based RL |
| **Model Access** | API only (no weights) | Requires weight access for gradients |
| **Algorithm** | Mutation + selection | REINFORCE policy gradient |
| **Attacker** | Any LLM via API (Claude, GPT) | Qwen with gradient access |
| **Update Mechanism** | Natural language feedback | Backpropagation through policy |
| **Optimization** | Discrete (select best variant) | Continuous (gradient descent) |
| **Scalability** | Expensive (many API calls) | More efficient (gradient signals) |

## Architecture

```
┌─────────────┐
│ Qwen Policy │ ← Policy gradient updates
│  (Attacker) │
└──────┬──────┘
       │ generates
       ↓
  ┌────────────┐
  │ Injection  │
  │  Variant   │
  └─────┬──────┘
        │ embedded in skill
        ↓
  ┌─────────────┐
  │Haiku (Victim)│ ← short task
  │   executes   │
  └──────┬───────┘
         │ output
         ↓
    ┌────────┐
    │  Judge │ → ASR (reward)
    └────┬───┘
         │ reward signal
         ↓
    ┌──────────┐
    │ Gradient │
    │ Compute  │
    └────┬─────┘
         │ ∇log π(a|s)
         └─────→ back to policy
```

## Algorithm: REINFORCE

The implementation uses REINFORCE (Williams, 1992), a classic policy gradient method:

1. **Rollout collection**:
   - For each injection ID and each rollout:
     - Sample injection variant from policy π_θ(a|s)
     - Track log probabilities: log π_θ(a|s)
     - Run victim (Haiku) with injection
     - Evaluate ASR → reward r

2. **Advantage estimation**:
   - Compute baseline b (moving average of rewards)
   - Advantage A = r - b

3. **Policy gradient**:
   - ∇J(θ) = E[A * ∇log π_θ(a|s)]
   - Average over rollouts

4. **Parameter update**:
   - θ ← θ + α * ∇J(θ)
   - Update baseline: b ← β*b + (1-β)*r

## Components

### RLConfig

Configuration dataclass with:
- `attacker_model`: Qwen variant (e.g., "qwen2.5-7b", "qwen2.5-14b")
- `victim_agent`: Agent scaffold ("claude")
- `victim_model`: Victim model ("haiku")
- `n_iterations`: Training iterations
- `rollouts_per_iteration`: Samples per iteration
- `learning_rate`: Policy optimizer learning rate (α)
- `gamma`: Discount factor (not used in REINFORCE, included for future)
- `baseline_decay`: Baseline moving average coefficient (β)

### PolicyGradientTrainer

Main training class with methods:

#### `generate_injection_with_policy()`
**Status**: PLACEHOLDER (to be implemented on cluster)

Samples injection from Qwen policy:
```python
# On cluster with Qwen loaded:
inputs = tokenizer(base_injection, return_tensors="pt")
outputs = model.generate(
    inputs,
    max_new_tokens=100,
    do_sample=True,
    temperature=1.0,
    return_dict_in_generate=True,
    output_scores=True,
)
# Track logprobs for gradient computation
logprobs = compute_logprobs(outputs.scores, outputs.sequences)
```

#### `evaluate_injection()`
**Status**: IMPLEMENTED (scaffold)

Runs victim agent (Haiku) with injection:
1. Build sandbox with injection embedded in skill
2. Run Haiku on short task (300s timeout)
3. Evaluate ASR → binary reward (1.0 or 0.0)

#### `collect_rollout()`
**Status**: IMPLEMENTED (scaffold)

Single rollout: generate → evaluate → compute advantage

#### `compute_policy_gradient()`
**Status**: PLACEHOLDER (to be implemented on cluster)

Computes REINFORCE gradient:
```python
# On cluster with Qwen:
loss = -torch.mean(advantages * logprobs)
loss.backward()
gradients = {name: param.grad for name, param in model.named_parameters()}
```

#### `update_policy()`
**Status**: PLACEHOLDER (to be implemented on cluster)

Applies gradients:
```python
# On cluster:
optimizer.step()
baseline = decay * baseline + (1-decay) * avg_reward
```

## Usage

### 1. Prepare Deployment Package (Local)

Run on your local machine to create the deployment package:

```bash
# Basic preparation
python3 experiments/ablations/rl_policy_gradient.py --prepare

# Custom configuration
python3 experiments/ablations/rl_policy_gradient.py --prepare \
    --attacker-model qwen2.5-14b \
    --victim-model haiku \
    --iterations 20 \
    --rollouts 10 \
    --learning-rate 1e-4 \
    --injection-id 1 --injection-id 5

# Smoke test (quick validation)
python3 experiments/ablations/rl_policy_gradient.py --prepare --smoke-test
```

This creates: `final_results/ablations/rl_policy_gradient/deployment/`

### 2. Transfer to Cluster

```bash
scp -r final_results/ablations/rl_policy_gradient/deployment/ \
    user@cluster:/path/to/workdir/
```

### 3. Cluster Setup

On the cluster:

```bash
# Load Qwen model (cluster-specific)
module load qwen/2.5-7b  # or similar

# Install dependencies
pip install transformers torch anthropic

# Set API key for victim (Haiku)
export ANTHROPIC_API_KEY=your_key_here
```

### 4. Implement Placeholders

Fill in the three placeholder methods in `rl_policy_gradient.py`:

1. **`generate_injection_with_policy()`**:
   - Load Qwen with transformers
   - Sample tokens from policy distribution
   - Track log probabilities

2. **`compute_policy_gradient()`**:
   - Compute loss = -mean(advantages * logprobs)
   - Backpropagate
   - Return gradients

3. **`update_policy()`**:
   - Apply gradients via optimizer
   - Update baseline

Example Qwen integration:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# Load Qwen
model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)

# In generate_injection_with_policy():
inputs = tokenizer(base_injection, return_tensors="pt").to(model.device)
with torch.no_grad():  # For rollout, no grad yet
    outputs = model.generate(...)

# In compute_policy_gradient():
# Re-forward through model WITH gradients
logits = model(**inputs).logits
logprobs = F.log_softmax(logits, dim=-1)
# Select logprobs for generated tokens
# Compute gradient

# In update_policy():
optimizer.step()
```

### 5. Run Training

```bash
cd deployment/
python3 rl_policy_gradient.py --run --config rl_config.json
```

## Expected Output

```
final_results/ablations/rl_policy_gradient/results/
├── training_history.json       # Reward curves, baseline over iterations
├── final_policy.pt            # Trained Qwen policy weights (save on cluster)
├── best_injections.json       # Best discovered injections per ID
└── rollout_logs/              # Detailed logs per iteration
```

### training_history.json Format

```json
{
  "config": {
    "attacker_model": "qwen2.5-7b",
    "victim_agent": "claude",
    "victim_model": "haiku",
    "n_iterations": 10,
    "rollouts_per_iteration": 5,
    "learning_rate": 1e-5
  },
  "history": [
    {
      "iteration": 0,
      "avg_reward": 0.23,
      "baseline": 0.0,
      "n_rollouts": 5
    },
    {
      "iteration": 1,
      "avg_reward": 0.41,
      "baseline": 0.23,
      "n_rollouts": 5
    },
    ...
  ]
}
```

## Visualization

After training, visualize results:

```bash
python3 scripts/plots/plot_rl_policy_gradient.py \
    final_results/ablations/rl_policy_gradient/results/
```

Generates:
- Reward curves over iterations
- Baseline convergence
- Per-injection improvement trajectories

## Hyperparameter Tuning

Key hyperparameters to tune:

| Parameter | Default | Range | Effect |
|-----------|---------|-------|--------|
| `learning_rate` | 1e-5 | 1e-6 to 1e-4 | Higher = faster but less stable |
| `rollouts_per_iteration` | 5 | 3-20 | More = better gradient estimate but slower |
| `baseline_decay` | 0.9 | 0.8-0.99 | Higher = smoother baseline |
| `n_iterations` | 10 | 5-50 | More = better optimization but expensive |

## Comparison: Evolutionary vs RL Policy Gradient

### When to Use Evolutionary Optimization

- No model weight access (API-only)
- Want quick experiments without cluster setup
- Exploring diverse approaches via natural language feedback
- Working with closed models (GPT, Claude, Gemini)

### When to Use RL Policy Gradient

- Have access to attacker model weights (Qwen)
- Want true gradient-based optimization
- Need sample efficiency (fewer evaluations)
- Want continuous optimization in latent space
- Have cluster resources for training

## Limitations & Future Work

### Current Limitations

1. **Binary rewards**: ASR is 0/1, sparse signal
2. **No multi-step**: Single generation step (could extend to multi-turn)
3. **Simple baseline**: Moving average (could use value network)
4. **No exploration bonus**: Could add entropy regularization

### Future Extensions

1. **PPO instead of REINFORCE**: Better sample efficiency
2. **Reward shaping**: Dense rewards (partial credit for partial success)
3. **Multi-objective**: Optimize ASR + stealth (lower detection)
4. **Transfer learning**: Pre-train on one victim, test on another
5. **Adversarial training**: Joint training of attacker and defender

## References

- Main paper: https://arxiv.org/pdf/2510.04885
- REINFORCE: Williams, R. J. (1992). Simple statistical gradient-following algorithms for connectionist reinforcement learning.
- PPO: Schulman et al. (2017). Proximal Policy Optimization Algorithms.
- Related: GCG, AutoDAN, PAIR, TAP (all use gradient-based optimization)
