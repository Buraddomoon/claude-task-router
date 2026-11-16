"""Opt-in two-call new/resume accounting check, maximum US$0.05 estimate."""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

from claude_task_router.config import Config
from claude_task_router.launcher import executable
from evaluation.measurements import stable
from evaluation.prospective import call, digest, sources_hash
from evaluation.real import ROOT, save

PROMPTS = ("Retorne somente OK.", "Repita exatamente a mesma resposta curta anterior.")
CAP = .025


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--claude-bin", default="claude")
    args = parser.parse_args(argv)
    report = dict(protocol="accounting-smoke-v1", planned_calls=2, max_estimated_cost_usd=.05,
                  max_cost_per_call_usd=CAP, prompts_sha256=[digest(p.encode()) for p in PROMPTS],
                  source_sha256=sources_hash(), python=platform.python_version(), platform=platform.system(),
                  savings_evaluation=False, records=[], stopped=None)
    if not args.real:
        print(json.dumps(report, indent=2))
        return 0
    if args.max_cost_usd != .05 or not args.output or args.output.exists() or not args.output.parent.is_dir():
        parser.error("Exige --max-cost-usd 0.05 e --output novo em diretório existente.")
    binary = executable(args.claude_bin)
    passed = False
    with tempfile.TemporaryDirectory(prefix="ctr-accounting-") as directory:
        root = Path(directory)
        config = root / "config.json"
        save(config, Config().snapshot())
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        previous = None
        session = None
        flags = ["-p", "--output-format", "json", "--tools", "", "--no-chrome", "--restricted",
                 "--effort", "low", "--max-turns", "1", "--max-budget-usd", str(CAP)]
        try:
            for turn, prompt in enumerate(PROMPTS, 1):
                if sum(r["cli_estimated_cost_usd"] or 0 for r in report["records"]) + CAP > .05:
                    report["stopped"] = "budget_headroom_exhausted"
                    break
                telemetry = root / f"telemetry-{turn}.json"
                command = [sys.executable, str(ROOT / "evaluation/observe_router.py"), str(telemetry),
                           "--claude-bin", binary, "--state-dir", str(root / "state"), "--config", str(config)]
                command += ["new", prompt] if turn == 1 else ["resume", session, prompt]
                command += ["--timeout", "80", "--", *flags]
                current, result = call(report, args.output, command, root, env, binary,
                                       case="S01", arm="routed", repetition=1, turn=turn, choice="sonnet",
                                       previous=previous, telemetry=telemetry, expected_session=session,
                                       timeout=90, expected_classifications=1 if turn == 1 else 0,
                                       state_dir=root / "state")
                row = report["records"][-1]
                row["functional_passed"] = isinstance(result, str) and result.strip() == "OK"
                session, previous = current["session_id"], current
                save(args.output, report)
                if not row["execution_ok"] or not row["functional_passed"] or row["measurement_issues"] or not row["model_confirmed"]:
                    report["stopped"] = "execution_or_measurement_failure"
                    break
                if row["cli_estimated_cost_usd"] > CAP:
                    report["stopped"] = "native_budget_overshoot"
                    break
            rows = report["records"]
            passed = (len(rows) == 2 and not report["stopped"] and
                      all(stable(r["client_before"], r["client_after"]) for r in rows) and
                      rows[0]["client_before"] == rows[1]["client_before"] and
                      rows[0]["session_id"] == rows[1]["session_id"])
        except KeyboardInterrupt:
            report["stopped"] = "interrupted"
        finally:
            report["summary"] = dict(accounting_check_passed=passed,
                                      known_cost_usd=sum(r["cli_estimated_cost_usd"] or 0 for r in report["records"]),
                                      measurements_complete=bool(report["records"]) and all(
                                          r["cli_estimated_cost_usd"] is not None and r["total_tokens"] is not None
                                          for r in report["records"]),
                                      savings_proven=False, api_invoice_usd=None, subscription_quota=None)
            save(args.output, report)
    print(json.dumps(report["summary"], indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
