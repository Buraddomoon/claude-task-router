"""Reproduce historical token/cost decomposition offline, without retuning."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from evaluation.measurements import TOKEN_FIELDS, number  # noqa: E402
from evaluation.real import save  # noqa: E402

ARTIFACTS = ("real-results-v3.json", "real-results-v4.json", "real-results-v4-interrupted.json")


def total(values, integer=False):
    values = list(values)
    valid = [number(v, integer) for v in values]
    known = sum(v for v in valid if v is not None)
    return dict(known=known, complete=bool(valid) and all(v is not None for v in valid),
                total=known if valid and all(v is not None for v in valid) else None)


def analyze(records):
    arms = {}
    for arm in ("baseline", "routed"):
        rows = [r for r in records if r["arm"] == arm]
        arms[arm] = dict(calls=len(rows), execution_failures=sum(not r["execution_ok"] for r in rows),
                         quality_passed=sum(r["quality_passed"] for r in rows),
                         cost_usd=total(r.get("cli_estimated_cost_usd") for r in rows),
                         seconds=total(r.get("duration_seconds") for r in rows),
                         total_tokens=total((r.get("total_tokens") for r in rows), integer=True),
                         tokens={key: total((r.get("token_usage", {}).get(key) for r in rows), integer=True)
                                 for key in TOKEN_FIELDS})
    differences = {}
    for key in TOKEN_FIELDS:
        base = arms["baseline"]["tokens"][key]["total"]
        routed = arms["routed"]["tokens"][key]["total"]
        differences[key] = routed - base if base is not None and routed is not None else None
    return dict(arms=arms, routed_minus_baseline_tokens=differences,
                native_router_overhead_seconds=None, resumed_marginal_cost_usd=None,
                version_verified_per_call=False, causal_cache_attribution_verified=False,
                api_invoice_usd=None, subscription_quota=None)


def audit():
    datasets = []
    for name in ARTIFACTS:
        raw = (ROOT / "evaluation" / name).read_bytes()
        source = json.loads(raw)
        datasets.append(dict(artifact=name, sha256=hashlib.sha256(raw).hexdigest(),
                             policy=source["policy"], planned_calls=source["planned_calls"],
                             stopped=source["stopped"], **analyze(source["records"])))
    return dict(protocol="historical-audit-v1", inference_calls=0, datasets=datasets,
                known_historical_cost_usd=sum(d["arms"][arm]["cost_usd"]["known"]
                                              for d in datasets for arm in ("baseline", "routed")),
                prospective_evaluation_status="pending_authorized_real_tasks_and_human_review",
                token_reduction_proven=False, general_savings_proven=False,
                policy_changed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    report = audit()
    if args.check:
        return 0 if json.loads(args.check.read_bytes()) == report else 1
    if args.output:
        if args.output.exists():
            parser.error("--output deve ser novo; preservar relatórios anteriores.")
        save(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
