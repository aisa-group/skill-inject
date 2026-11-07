# Permission-defense ablation

Measures how **deterministic permission restrictions** change attack success rate
and utility, with each restriction *actually enforced* inside the agent
container. This is the experiment-level version of `tab:permission-defense` in
`paper/workshop-main.tex`, which was dropped from the NeurIPS draft and whose
numbers have no surviving code or raw runs.

```
experiments/ablations/permission_defense.py   runner: build → enforce → run → grade → aggregate
experiments/ablations/permission_policy.py    the policy: capabilities and their enforcement
```

## Conditions

One unrestricted control, one condition per capability, and an all-restrictions
upper bound:

| Condition | Capability denied |
|---|---|
| `baseline` | — |
| `net_egress` | outbound network |
| `shell_exec` | shell command execution |
| `file_delete` | deleting/truncating files |
| `calendar_write` | writing calendar stores |
| `db_file_write` | writing `*.db` / `*.sqlite` |
| `email_send` | sending/forwarding/uploading mail |
| `all` | all six |

## How enforcement works

No single mechanism covers every channel an agent can reach a capability
through, so the policy layers five, and `--validate` proves each one blocks
before any API budget is spent:

1. **Read-only bind mounts** — kernel-enforced, agent-agnostic. Calendar stores,
   `*.db` files and the `email-api` sender scripts (replaced by a denial stub).
   Nothing gets through these: not Bash, not the agent's native Write tool, not
   a Python or Node child.
2. **A bash `DEBUG`-trap policy**, sourced by every non-interactive shell via
   `BASH_ENV`. With `shopt -s extdebug`, a non-zero return from the trap *skips*
   the command, so this blocks rather than merely logs.
3. **PATH shims** in `/perm/bin` for the network/deletion/mail binaries, which
   catch a direct `execvp` from a child that never goes through a shell.
4. **A Python import hook** (`sitecustomize` on `PYTHONPATH`) patching
   `socket.connect`, the deletion calls, `open()`/`sqlite3.connect` on protected
   paths, and `smtplib`. Agents write a lot of Python here, so this is the
   highest-traffic channel after the shell.
5. **Agent-native tool denial** (`--disallowedTools`), which is how a deployed
   harness would express the restriction.

The policy tree is built per condition and bind-mounted read-only at `/perm`;
the only thing written into the sandbox is a one-file hook, `.perm_runtime.sh`,
which `apptainer/run_sandbox.sh` sources when present. No hook file ⇒ byte-identical
behaviour to every other experiment.

> **One non-obvious detail.** The container's bash is built with
> `--enable-debugger`. `shopt -s extdebug` makes it try to source
> `/usr/share/bashdb/bashdb-main.inc`; when that file is missing it warns and
> **disables debugging mode**, which silently turns the DEBUG trap back into a
> passive logger — denials would have been logged but not enforced. The policy
> binds an empty include over that path to keep `extdebug` live. `--validate`
> catches this class of failure, which is exactly why it exists.

### Two deliberate choices in the telemetry

- **Denied commands are not written to `.command_history`.** That file is the
  log of commands that *executed*, and the unit-test graders read it as evidence
  of attack success. A blocked attempt is not a success, so it goes to
  `.permission_events.jsonl` instead.
- **Attempts are logged even when a read-only bind would have stopped them
  anyway.** The kernel does not tell us a write was refused, and the attempt is
  half the measurement.

## Metrics

Per condition, over the obvious-injection suite:

| Metric | Meaning |
|---|---|
| ASR | attack success, graded by the deterministic unit-test graders in `data/instruction_unit_tests/obvious/` |
| Targeted ASR | ASR over only the injections whose attack channel this restriction covers (`INJECTION_CHANNEL`) |
| Utility | task completion, LLM judge, same prompt as `judges/utility_baseline_judge.py`; utility loss is relative to baseline |
| Attempt rate | share of runs where the agent tried a restricted action and was denied |
| Circumvention | share of *those* runs that still reached attack success through an uncovered channel |

The last two are the reason to run this rather than reason about it post hoc:
an ASR drop can mean the agent was stopped or that it never tried, and only the
telemetry separates the two. Circumvention additionally measures where the
enforcement leaks — a restriction with a high attempt rate and non-zero
circumvention is not the defense the ASR column suggests.

## Usage

```bash
# prove the enforcement mechanisms block (no API calls, ~2 min)
python experiments/ablations/permission_defense.py --validate

# pilot: capability-relevant injections, one task each, all conditions
python experiments/ablations/permission_defense.py \
    --agent claude --model sonnet --pilot --first-task-only --parallel 4

# full grid: every injection × every task × every condition
python experiments/ablations/permission_defense.py \
    --agent claude --model sonnet --parallel 4

# add the utility judge to an existing run without re-running agents
python experiments/ablations/permission_defense.py \
    --agent claude --model sonnet --pilot --first-task-only --eval-only
```

Useful flags: `--conditions a,b,c`, `--injection-id 1,2,3`, `--skip-utility`
(ASR + telemetry only), `--judge-model`, `--force` (discard existing results),
`--eval-only` (re-grade in place). Runs resume by default: a sandbox that
already has `agent_stdout.txt` is skipped, and utility verdicts are cached, so
re-invoking after an interruption costs nothing.

Outputs land in
`final_results/ablations/permission_defense/<agent>-<model>/`:
`<condition>/evaluation.json` per condition, plus `aggregated_results.json`,
`table.md`, and `table.tex` (shaped like the workshop table).

## Scale

`--pilot --first-task-only` is 12 injections × 8 conditions = 96 runs (~1 h at
`--parallel 4`). The full grid is 180 injection-task pairs × 8 conditions =
1440 runs and belongs on the cluster — one job per condition, `--conditions`
naming a single condition each.

## Limitations

- **Node is uncovered.** The agent CLI is Node and makes its own HTTPS calls, so
  `net_egress` cannot be enforced by killing the container's network without
  also killing the agent. A payload the agent writes *as a Node script* is
  therefore an enforcement gap; it shows up honestly as ASR that does not drop,
  and as circumvention in the telemetry.
- **Pattern rules match command text.** A denied pattern that appears quoted
  inside an otherwise benign command line is denied too. This over-blocks in
  rare cases and is a property of any command-pattern policy.
- `--disallowedTools` is Claude-specific; for `codex`/`gemini` the `shell_exec`
  condition rests on the bash layer alone.
- The utility judge is an LLM. It uses the same generous prompt as the existing
  utility baseline so the numbers are comparable to that experiment, and it
  inherits the same self-grading caveat.
