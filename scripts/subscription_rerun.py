#!/usr/bin/env python3
"""Plan and run versioned, subscription-only benchmark reruns."""
from __future__ import annotations
import argparse, datetime as dt, json, os, subprocess, sys, time
from dataclasses import asdict, dataclass
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SIF = ROOT / "apptainer" / "instruct-bench-agent.sif"
DEFAULT_OUTPUT = ROOT / "reruns" / "subscription_ee64f60"
SECONDS_PER_CASE = {"claude": 48.4, "codex": 50.0}
MODEL_SETS = {
    "claude": (
        "claude-sonnet-4-5",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001",
    ),
    "codex": ("gpt-5.2-codex", "gpt-5.1-codex-mini", "gpt-5.2"),
}
PROBE_MODELS = {"codex": ("gpt-5.1",), "claude": ()}
@dataclass(frozen=True)
class Workload:
    name: str
    cases: int
    command: tuple[str, ...]
    result_glob: str
    profile: str = "rebuttal"
def py(*args: str) -> tuple[str, ...]: return (sys.executable, *args)
def workloads(provider: str, model: str, profile: str) -> list[Workload]:
    slug = f"{provider}-{model}".replace(".", "-")
    raw_slug = f"{provider}-{model}"
    common = ("--agent", provider, "--model", model, "--parallel", "1")
    runtime = ("--runtime", "apptainer", "--sif", str(SIF), "--auth", "subscription")
    if profile == "smoke":
        return [
            Workload(
                "contextual_smoke",
                1,
                py(
                    "experiments/contextual.py", *common, *runtime,
                    "--policy", "normal", "--smoke-test", "--skip-eval",
                ),
                f"contextual/{slug}/normal/INST-1_*/agent_stdout.txt",
                "smoke",
            )
        ]
    rows = [
        Workload("contextual", 417, py("experiments/contextual.py", *common, *runtime, "--skip-eval"), f"contextual/{slug}/**/*/agent_stdout.txt"),
        Workload("obvious", 180, py("experiments/obvious.py", *common, *runtime, "--skip-eval"), f"obvious/{slug}/**/*/agent_stdout.txt"),
        Workload("utility_baseline", 116, py("experiments/utility_baseline.py", *common, *runtime, "--skip-eval"), f"utility_baseline/{raw_slug}/**/*/agent_stdout.txt"),
    ]
    if profile == "rebuttal":
        rows.append(Workload("permission_defense_pilot", 112, py("experiments/ablations/permission_defense.py", "--agent", provider, "--model", model, "--pilot", "--first-task-only", "--parallel", "1", "--skip-utility", "--no-preflight"), f"ablations/permission_defense/{slug}/**/*/agent_stdout.txt"))
    else:
        rows += [
            Workload("bo4_bytask",20,py("experiments/ablations/bo4_bytask.py","--agent",provider,"--model",model),f"ablations/bo4_bytask/{slug}/**/*/agent_stdout.txt","full"),
            Workload("bo5_byline",180,py("experiments/ablations/bo5_byline.py","--agent",provider,"--model",model),f"ablations/bo5_byline/{slug}/**/*/agent_stdout.txt","full"),
            Workload("bo5_bytask",180,py("experiments/ablations/bo5_bytask.py","--agent",provider,"--model",model),f"ablations/bo5_bytask/{slug}/**/*/agent_stdout.txt","full"),
            Workload("bo5_combined",35,py("experiments/ablations/bo5_combined.py","--agent",provider,"--model",model),f"ablations/bo5_combined/{slug}/**/*/agent_stdout.txt","full"),
            Workload("domain_variation",720,py("experiments/ablations/domain_variation.py","--agent",provider,"--model",model),f"ablations/domain_variation/{slug}/**/*/agent_stdout.txt","full"),
            Workload("multi_skill_dilution",50,py("experiments/ablations/multi_skill_dilution.py","--agent",provider,"--model",model,"--runtime","apptainer","--sif",str(SIF)),f"ablations/multi_skill_dilution/{slug}/**/*/agent_stdout.txt","full"),
            Workload("obvious_error_bars",50,py("experiments/ablations/obvious_injection_error_bars.py","--agent",provider,"--model",model),f"ablations/obvious_error_bars/{slug}/**/*/agent_stdout.txt","full"),
            Workload("obvious_error_bars_remaining",650,py("experiments/ablations/obvious_injection_error_bars_remaining.py","--agent",provider,"--model",model),f"ablations/obvious_error_bars_remaining/{slug}/**/*/agent_stdout.txt","full"),
            Workload("phrasing_variants",70,py("experiments/ablations/phrasing_variants.py","--agent",provider,"--model",model),f"ablations/phrasing_variants/{slug}/**/*/agent_stdout.txt","full"),
            Workload("script_vs_direct",139,py("experiments/ablations/script_vs_direct.py","--agent",provider,"--model",model,"--parallel","1"),f"ablations/script_vs_direct/{slug}/**/*/agent_stdout.txt","full"),
            Workload("skill_trust_prompting",15,py("experiments/ablations/skill_trust_prompting.py","--agent",provider,"--model",model),f"ablations/skill_trust_prompting/{slug}/**/*/agent_stdout.txt","full"),
            Workload("template_variation",115,py("experiments/ablations/template_variation.py","--agent",provider,"--model",model),f"ablations/template_variation/{slug}/**/*/agent_stdout.txt","full"),
            Workload("permission_defense_full",1440,py("experiments/ablations/permission_defense.py","--agent",provider,"--model",model,"--parallel","1","--skip-utility","--no-preflight"),f"ablations/permission_defense/{slug}/**/*/agent_stdout.txt","full"),
        ]
    return rows
def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,indent=2)+"\n"); tmp.replace(path)
def reconcile(root: Path, pattern: str) -> dict:
    completed = sum(1 for _ in root.glob(pattern))
    literal_parts = []
    for part in Path(pattern).parts:
        if any(char in part for char in "*?["):
            break
        literal_parts.append(part)
    base = root.joinpath(*literal_parts)
    statuses = {}
    for log in base.rglob("run_status.jsonl") if base.exists() else ():
        for line in log.read_text(errors="ignore").splitlines():
            try: row = json.loads(line)
            except json.JSONDecodeError: continue
            if row.get("event") == "sandbox_complete":
                statuses[f"{log.parent}:{row.get('sandbox_id')}"] = bool(row.get("success"))
    technical = 0
    for ev in base.rglob("evaluation*.json") if base.exists() else ():
        try: rows = json.loads(ev.read_text()).get("results", [])
        except (OSError, json.JSONDecodeError): continue
        technical += sum(1 for row in rows if (row.get("score") or row.get("injection_score") or row.get("verdict")) == "technical")
    return {"completed": completed, "successful": sum(statuses.values()),
            "failed": len(statuses) - sum(statuses.values()), "technical": technical}
def estimate(profile: str) -> dict:
    providers={}
    for provider, models in MODEL_SETS.items():
        cases_per_model = sum(x.cases for x in workloads(provider, models[0], profile))
        cases = cases_per_model * len(models)
        seconds = cases * SECONDS_PER_CASE[provider]
        providers[provider] = {
            "models": list(models),
            "cases_per_model": cases_per_model,
            "cases": cases,
            "serial_hours": round(seconds / 3600, 2),
        }
    return {"profile":profile,"providers":providers,"total_cases":sum(x["cases"] for x in providers.values()),"serial_hours":round(sum(x["serial_hours"] for x in providers.values()),2),"wall_hours_one_concurrent_per_provider":round(max(x["serial_hours"] for x in providers.values()),2),"assumptions":{"seconds_per_case":SECONDS_PER_CASE,"subscription_concurrency_per_provider":1}}
def run_model(provider: str, model: str, profile: str, output: Path) -> int:
    commit=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    ledger_path=output/"ledgers"/f"{provider}-{model.replace(chr(46), chr(45))}.json"
    try: ledger=json.loads(ledger_path.read_text())
    except (FileNotFoundError,json.JSONDecodeError): ledger={"provider":provider,"model":model,"auth":"subscription","repository_commit":commit,"profile":profile,"workloads":{}}
    env=os.environ.copy(); env.update({"SKILL_INJECT_RESULTS_DIR":str(output/"results"),"SKILL_INJECT_RUNTIME":"apptainer","SKILL_INJECT_AUTH":"subscription","SKILL_INJECT_SIF":str(SIF)})
    for item in workloads(provider, model, profile):
        prior=ledger["workloads"].get(item.name,{}); before=reconcile(output/"results",item.result_glob); completed=before["completed"]
        if prior.get("status")=="complete" and before["successful"]>=item.cases: continue
        record={**asdict(item),"command":list(item.command),"planned":item.cases,"completed_before":completed,"counts_before":before,"status":"running","started_utc":dt.datetime.now(dt.timezone.utc).isoformat()}
        ledger["workloads"][item.name]=record; atomic_json(ledger_path,ledger); started=time.monotonic()
        proc=subprocess.run(item.command,cwd=ROOT,env=env); after=reconcile(output/"results",item.result_glob); completed_after=after["completed"]
        record.update({"returncode":proc.returncode,"completed":completed_after,"successful":after["successful"],"failed":after["failed"],"technical":after["technical"],"missing":max(0,item.cases-after["successful"]),"elapsed_seconds":round(time.monotonic()-started,2),"finished_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"status":"complete" if proc.returncode==0 and after["successful"]>=item.cases else "failed"})
        atomic_json(ledger_path,ledger)
        if record["status"]!="complete": return proc.returncode or 1
    return 0

def run(provider: str, profile: str, output: Path, selected_model: str | None = None) -> int:
    models = (selected_model,) if selected_model else MODEL_SETS[provider]
    for model in models:
        rc = run_model(provider, model, profile, output)
        if rc:
            return rc
    return 0

def reconcile_ledgers(output: Path) -> int:
    ledger_dir = output / "ledgers"
    changed = 0
    for ledger_path in sorted(ledger_dir.glob("*.json")):
        ledger = json.loads(ledger_path.read_text())
        provider, model = ledger["provider"], ledger["model"]
        profile = ledger.get("profile", "smoke")
        by_name = {item.name: item for item in workloads(provider, model, profile)}
        for name, record in ledger.get("workloads", {}).items():
            item = by_name.get(name)
            if item is None:
                continue
            counts = reconcile(output / "results", item.result_glob)
            record.update(counts)
            record["missing"] = max(0, item.cases - counts["successful"])
            record["status"] = "complete" if counts["successful"] >= item.cases else "failed"
        atomic_json(ledger_path, ledger)
        changed += 1
    print(f"Reconciled {changed} ledger(s) from result artifacts")
    return 0

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--profile",choices=["smoke","rebuttal","full"],default="rebuttal"); ap.add_argument("--provider",choices=list(MODEL_SETS)); ap.add_argument("--model"); ap.add_argument("--output",type=Path,default=DEFAULT_OUTPUT); ap.add_argument("--execute",action="store_true"); ap.add_argument("--reconcile",action="store_true"); ap.add_argument("--json",action="store_true"); args=ap.parse_args(); plan=estimate(args.profile)
    if args.reconcile:
        return reconcile_ledgers(args.output.resolve())
    if args.json: print(json.dumps(plan,indent=2))
    else:
        print(
            f"{args.profile}: {plan['total_cases']} cases, "
            f"{plan['serial_hours']} serial h, "
            f"{plan['wall_hours_one_concurrent_per_provider']} h "
            "at one concurrent run/provider"
        )
    if not args.execute:return 0
    if not args.provider:ap.error("--execute requires --provider")
    
    if args.model and args.model not in (*MODEL_SETS[args.provider], *PROBE_MODELS[args.provider]):
        ap.error("model is not in the paper model set or approved availability probes")
    return run(args.provider,args.profile,args.output.resolve(),args.model)
if __name__=="__main__":raise SystemExit(main())
