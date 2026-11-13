"""Opt-in, budgeted Claude Code comparison. The default only prints a plan."""

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claude_task_router.classifier import classify  # noqa: E402
from claude_task_router.config import Config  # noqa: E402
from claude_task_router.launcher import executable  # noqa: E402
from claude_task_router.state import matches_choice  # noqa: E402


def quality(case, text):
    try:
        value = json.loads(text)
        if case["kind"] == "json":
            return json.dumps(value, sort_keys=True) == json.dumps(case["expected"], sort_keys=True)
        if case["kind"] == "translation":
            return (isinstance(value, dict) and set(value) == {"text"}
                    and isinstance(value["text"], str)
                    and value["text"].strip().rstrip(".").casefold() in
                    {item.casefold() for item in case["expected"]})
        if not isinstance(value, dict) or set(value) != {"code"} or not isinstance(value["code"], str):
            return False
        if len(value["code"].encode()) > 4096:
            return False
        tree = ast.parse(value["code"])
        if case["kind"] == "rename":
            return ast.dump(tree) == ast.dump(ast.parse(case["expected"]))
        allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
                   ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Name, ast.Load, ast.Constant)
        nodes = list(ast.walk(tree))
        if len(nodes) > 256 or any(not isinstance(node, allowed) for node in nodes):
            return False
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
            return False
        fn = tree.body[0]
        if (fn.name != "pages" or fn.decorator_list or fn.returns or len(fn.body) != 1
                or not isinstance(fn.body[0], ast.Return) or fn.args.defaults or fn.args.kw_defaults
                or fn.args.posonlyargs or fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs
                or [arg.arg for arg in fn.args.args] != ["total", "size"]
                or any(arg.annotation for arg in fn.args.args)):
            return False
        for node in nodes:
            if isinstance(node, ast.Name) and node.id not in {"total", "size"}:
                return False
            if isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 10**9):
                return False
        scope = {"__builtins__": {}}
        exec(compile(tree, "<restricted-quality-check>", "exec"), scope)
        return all(type(scope["pages"](total, size)) is int and scope["pages"](total, size) == expected
                   for total, size, expected in ((0, 10, 0), (1, 10, 1), (10, 10, 1), (11, 10, 2), (9999, 100, 100)))
    except (ValueError, TypeError, SyntaxError, KeyError, ArithmeticError, NameError, RecursionError):
        return False


def execute(command, cwd, env):
    try:
        child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError:
        return 2, ""  # Record a failed spawn instead of discarding the attempted row.
    try:
        out, _ = child.communicate(timeout=100)
        return child.returncode, out
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.communicate(timeout=7)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
        if sys.exc_info()[0] is KeyboardInterrupt:
            raise
        return 124, ""


def summarize(records, planned):
    totals = {}
    for arm in ("baseline", "routed"):
        selected = [r for r in records if r["arm"] == arm]
        totals[arm] = dict(calls=len(selected), quality_passed=sum(r["quality_passed"] for r in selected),
                           cost_usd=sum(r["cli_estimated_cost_usd"] or 0 for r in selected),
                           seconds=sum(r["duration_seconds"] for r in selected),
                           tokens=sum(r["total_tokens"] or 0 for r in selected),
                           measurements_complete=all(r["cli_estimated_cost_usd"] is not None
                                                     and r["total_tokens"] is not None for r in selected))
    complete = (len(records) == planned and all(r["execution_ok"] and r.get("model_confirmed", False) for r in records)
                and all(totals[arm]["measurements_complete"] for arm in totals))
    quality_ok = complete and totals["routed"]["quality_passed"] == totals["baseline"]["quality_passed"] == planned // 2
    reductions = {}
    for metric in ("cost_usd", "seconds", "tokens"):
        base, routed = totals["baseline"][metric], totals["routed"][metric]
        reductions[metric] = round(100 * (base - routed) / base, 3) if base and quality_ok else None
    paired = {}
    for record in records:
        paired.setdefault((record.get("case"), record.get("repetition")), []).append(record)
    valid_pairs = [pair for pair in paired.values() if len(pair) == 2 and
                   {r["arm"] for r in pair} == {"baseline", "routed"} and
                   all(r["quality_passed"] and r["execution_ok"] for r in pair)]
    pair_totals = {arm: dict(cost_usd=sum(r["cli_estimated_cost_usd"] or 0 for pair in valid_pairs for r in pair if r["arm"] == arm),
                            seconds=sum(r["duration_seconds"] for pair in valid_pairs for r in pair if r["arm"] == arm))
                   for arm in totals}
    return dict(complete=complete, all_quality_passed=quality_ok, totals=totals,
                quality_valid_pairs=len(valid_pairs), quality_valid_pair_totals=pair_totals,
                observed_reduction_percent=reductions,
                note="Microtarefas sintéticas; custo estimado do CLI, não fatura. Sem garantia geral de qualidade/economia.")


def save(path, report):
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10 or not math.isfinite(args.max_cost_usd) or not 0 < args.max_cost_usd <= 10:
        parser.error("repetitions: 1–10; max-cost-usd: positivo, até 10.")
    raw = Path(__file__).with_name("real-cases.json").read_bytes()
    cases = json.loads(raw)
    planned = len(cases) * 2 * args.repetitions
    report = dict(protocol="real-v1", cases_sha256=hashlib.sha256(raw).hexdigest(),
                  policy=classify("help").policy, python=platform.python_version(), platform=platform.system(),
                  planned_calls=planned, repetitions=args.repetitions, max_estimated_cost_usd=args.max_cost_usd,
                  router_inference_calls_per_classification=0, router_context_instructions=0,
                  plan=[dict(id=c["id"], expected_tier=c["tier"], routed=classify(c["prompt"]).to_dict()) for c in cases],
                  records=[], stopped=None)
    if not args.real:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.output is None or args.output.exists() or not args.output.parent.is_dir():
        parser.error("--real exige --output novo em diretório existente.")
    binary = executable(args.claude_bin)
    report["claude_version"] = subprocess.run([binary, "--version"], capture_output=True,
                                              text=True, timeout=15, check=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="ctr-real-") as raw_root:
        root = Path(raw_root)
        project = root / "project"
        project.mkdir()
        frozen = root / "frozen"
        shutil.copytree(ROOT / "claude_task_router", frozen / "claude_task_router",
                        ignore=shutil.ignore_patterns("__pycache__"))
        sources = sorted((frozen / "claude_task_router").glob("*.py"))
        report["source_sha256"] = hashlib.sha256(b"".join(p.name.encode() + p.read_bytes() for p in sources)).hexdigest()
        config = root / "config.json"
        config.write_text(json.dumps(Config().snapshot()))
        env = dict(os.environ, PYTHONPATH=str(frozen))
        cap = .05
        flags = ["-p", "--output-format", "json", "--tools", "", "--no-chrome", "--restricted",
                 "--effort", "low", "--max-turns", "1", "--max-budget-usd", str(cap)]
        try:
            for repetition in range(args.repetitions):
                for index, case in enumerate(cases):
                    order = ("baseline", "routed") if (index + repetition) % 2 == 0 else ("routed", "baseline")
                    for arm in order:
                        spent = sum(r["cli_estimated_cost_usd"] or 0 for r in report["records"])
                        if spent + cap > args.max_cost_usd:
                            report["stopped"] = "budget_headroom_exhausted"
                            raise StopIteration
                        decision = classify(case["prompt"])
                        choice = "sonnet" if arm == "baseline" else decision.model
                        if arm == "baseline":
                            command = [binary, "--model", choice, "--no-session-persistence", *flags, "--", case["prompt"]]
                        else:
                            command = [sys.executable, "-m", "claude_task_router", "--claude-bin", binary,
                                       "--state-dir", str(root / "state"), "--config", str(config),
                                       "new", case["prompt"], "--timeout", "90", "--", *flags]
                        start = time.monotonic()
                        code, output = execute(command, project, env)
                        duration = round(time.monotonic() - start, 4)
                        try:
                            payload = json.loads(output)
                            if not isinstance(payload, dict):
                                raise ValueError()
                        except ValueError:
                            payload = {}
                        cost = payload.get("total_cost_usd")
                        cost = float(cost) if type(cost) in (float, int) and math.isfinite(cost) and cost >= 0 else None
                        usage = payload.get("usage", {})
                        tokens = {key: usage.get(key) for key in ("input_tokens", "cache_creation_input_tokens",
                                                               "cache_read_input_tokens", "output_tokens")}
                        valid_tokens = all(type(v) is int and v >= 0 for v in tokens.values())
                        models = list(payload.get("modelUsage", {}))
                        ok = code == 0 and payload.get("subtype") == "success" and not payload.get("is_error")
                        passed = ok and quality(case, payload.get("result", ""))
                        record = dict(case=case["id"], repetition=repetition + 1, arm=arm, requested_model=choice,
                                      effective_models=models, model_confirmed=bool(models) and all(matches_choice(choice, m) for m in models),
                                      exit_code=code, execution_ok=ok, quality_passed=passed, native_turns=payload.get("num_turns"),
                                      duration_seconds=duration, cli_estimated_cost_usd=cost, token_usage=tokens,
                                      total_tokens=sum(tokens.values()) if valid_tokens else None)
                        report["records"].append(record)
                        report["summary"] = summarize(report["records"], planned)
                        save(args.output, report)
                        print(json.dumps(record), flush=True)
                        if cost is None:
                            report["stopped"] = "missing_cost_measurement"
                            raise StopIteration
        except StopIteration:
            pass
        except KeyboardInterrupt:
            report["stopped"] = "interrupted"
        finally:
            report["summary"] = summarize(report["records"], planned)
            save(args.output, report)
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["all_quality_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
