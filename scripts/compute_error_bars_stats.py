#!/usr/bin/env python3
"""Compute per-model error-bar statistics from existing K=5 runs."""
import json
from pathlib import Path
from random import Random

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIRS = [
    PROJECT_ROOT / "final_results" / "ablations" / "obvious_error_bars",
    PROJECT_ROOT / "final_results" / "ablations" / "obvious_error_bars_remaining",
]

PAPER_MODELS = {
    "codex-gpt-5-2-codex":               "GPT-5.2-Codex",
    "codex-gpt-5-1-codex-mini":          "GPT-5.1-Codex-Mini",
    "codex-gpt-5-2":                     "GPT-5.2",
    "claude-sonnet":                     "Sonnet 4.5",
    "claude-claude-opus-4-5-20251101":   "Opus 4.5",
    "claude-haiku":                      "Haiku 4.5",
    "gemini-gemini-3-flash-preview":     "Gemini 3 Flash",
    "gemini-gemini-3-pro-preview":       "Gemini 3 Pro",
}


def find_aggregated(slug):
    candidates = []
    for base in BASE_DIRS:
        path = base / slug / "aggregated_results.json"
        if path.exists():
            candidates.append(path)
    if not candidates:
        return None
    best, best_count = None, -1
    for p in candidates:
        try:
            d = json.loads(p.read_text())
            # Use number of successful runs in all_runs (more = preferred).
            n = sum(1 for r in d.get("all_runs", []) if r.get("data", {}).get("results"))
            if n > best_count:
                best, best_count = p, n
        except Exception:
            continue
    return best


def reaggregate(d):
    """Recompute per-injection ASR including zero-success injections."""
    declared_ids = set(d.get("injection_ids", []))
    all_ids = set(declared_ids)
    for run_data in d.get("all_runs", []):
        for r in run_data.get("data", {}).get("results", []):
            if r.get("injection_id") is not None:
                all_ids.add(r["injection_id"])

    n_runs = d.get("n_runs", len(d.get("all_runs", [])))
    counts = {iid: 0 for iid in all_ids}
    for run_data in d.get("all_runs", []):
        succeeded = set()
        for r in run_data.get("data", {}).get("results", []):
            score = r.get("score") or r.get("injection_score") or ""
            if score == "attack_success":
                succeeded.add(r.get("injection_id"))
        for iid in succeeded:
            if iid in counts:
                counts[iid] += 1
    return {iid: counts[iid] / n_runs for iid in counts}, n_runs


def bootstrap_ci(asrs, n_iter=10000, seed=0):
    if not asrs:
        return (0.0, 0.0)
    rng = Random(seed)
    n = len(asrs)
    means = sorted(sum(asrs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_iter))
    return means[int(0.025 * n_iter)], means[int(0.975 * n_iter)]


def main():
    rows = []
    for slug, display in PAPER_MODELS.items():
        agg_path = find_aggregated(slug)
        if not agg_path:
            rows.append({"model": display, "status": "NO DATA"})
            continue
        d = json.loads(agg_path.read_text())
        per_inj_asrs, K = reaggregate(d)
        injection_asrs = list(per_inj_asrs.values())
        per_inj_sd = [(a * (1 - a)) ** 0.5 for a in injection_asrs]
        if not injection_asrs:
            rows.append({"model": display, "status": "EMPTY agg", "path": str(agg_path)})
            continue
        mean_asr = sum(injection_asrs) / len(injection_asrs)
        ci_lo, ci_hi = bootstrap_ci(injection_asrs)
        rows.append({
            "model": display,
            "K": K,
            "n_inj": len(injection_asrs),
            "mean_asr_pct": mean_asr * 100,
            "ci_lo_pct": ci_lo * 100,
            "ci_hi_pct": ci_hi * 100,
            "ci_half_pp": (ci_hi - ci_lo) / 2 * 100,
            "mean_per_inj_sd_pp": sum(per_inj_sd) / len(per_inj_sd) * 100,
            "path": str(agg_path),
        })

    print(f"{'Model':<22} {'K':>3} {'n_inj':>5} {'ASR':>6} {'95% CI':>18} {'per-inj SD':>14}")
    print("-" * 80)
    full = [r for r in rows if "status" not in r]
    for r in rows:
        if "status" in r:
            print(f"{r['model']:<22} {r['status']}")
            continue
        ci = f"[{r['ci_lo_pct']:5.1f}, {r['ci_hi_pct']:5.1f}]"
        print(f"{r['model']:<22} {r['K']:>3} {r['n_inj']:>5} {r['mean_asr_pct']:>5.1f}% {ci:>18} {r['mean_per_inj_sd_pp']:>12.1f}pp")
    print()
    if full:
        print(f"Across-model mean per-injection SD : {sum(r['mean_per_inj_sd_pp'] for r in full)/len(full):.1f}pp")
        print(f"Across-model CI half-width range   : {min(r['ci_half_pp'] for r in full):.1f}pp – {max(r['ci_half_pp'] for r in full):.1f}pp")
        print(f"Across-model mean ASR              : {sum(r['mean_asr_pct'] for r in full)/len(full):.1f}%")


if __name__ == "__main__":
    main()
