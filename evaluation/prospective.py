"""Frozen private task cohorts. Planning/freezing never performs inference."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import time
import uuid

from claude_task_router.classifier import validate_prompt
from claude_task_router.config import Config
from claude_task_router.launcher import executable
from claude_task_router.privacy import private_directory
from claude_task_router.state import Store, matches_choice
from evaluation.measurements import marginal, provenance, snapshot, stable
from evaluation.real import ROOT, execute, save

PROTOCOL = Path(__file__).with_name("prospective-protocol.json")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sources_hash():
    files = sorted((ROOT / "claude_task_router").glob("*.py")) + sorted((ROOT / "evaluation").glob("*.py"))
    return digest(b"".join(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() for path in files))


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, check=True).stdout


def freeze(manifest_path, protocol):
    """Return allowlisted metadata only; do not copy arbitrary manifest fields."""
    if manifest_path.resolve().is_relative_to(ROOT):
        raise ValueError("O manifesto privado deve ficar fora do repositório do roteador.")
    raw = manifest_path.read_bytes()
    data = json.loads(raw)
    if data.get("authorized") is not True or data.get("not_used_for_calibration") is not True:
        raise ValueError("São necessárias autorização das tarefas e declaração de conjunto reservado.")
    tasks = data.get("tasks", [])
    if Counter(t.get("category") for t in tasks) != Counter(protocol["categories"]):
        raise ValueError("A amostra deve cumprir as categorias e quantidades congeladas.")
    known = {digest(c["prompt"].encode()) for c in json.loads((ROOT / "evaluation/real-cases.json").read_bytes())}
    for corpus in ("corpus.json", "conversation-boundaries.json", "conversation-boundaries-v2.json"):
        # Match every string in public calibration artifacts, not only one
        # assumed schema; semantic/private overlap still requires declaration.
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)
        known.update(digest(s.encode()) for s in strings(json.loads((ROOT / "evaluation" / corpus).read_bytes())))
    metadata = []
    identifiers = set()
    for task in tasks:
        identifier = task.get("id", "")
        if not re.fullmatch(r"T\d{2}", identifier) or identifier in identifiers:
            raise ValueError("IDs devem ser opacos e únicos: T01, T02, ...")
        identifiers.add(identifier)
        project = Path(task["project"]).resolve()
        if git(project, "status", "--porcelain").strip():
            raise ValueError("Os snapshots dos projetos devem estar limpos.")
        commit = task["commit"]
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit) or git(project, "rev-parse", "HEAD").decode().strip() != commit:
            raise ValueError("O commit deve identificar exatamente o snapshot atual.")
        prompts = task["prompts"]
        checks = task["acceptance"]
        if len(prompts) != protocol["turns_per_task"] or len(checks) != len(prompts):
            raise ValueError("Cada tarefa exige dois prompts e dois comandos de aceitação.")
        hashes = []
        for source in prompts:
            path = Path(source).resolve()
            if path.is_relative_to(ROOT):
                raise ValueError("Prompts privados devem ficar fora do repositório do roteador.")
            prompt_raw = path.read_bytes()
            prompt = prompt_raw.decode("utf-8")
            validate_prompt(prompt)
            if len(prompt.encode()) > 96 * 1024:
                raise ValueError("Prompt excede o limite do launcher.")
            hashed = digest(prompt_raw)
            if hashed in known:
                raise ValueError("Um prompt já pertence ao corpus conhecido.")
            hashes.append(hashed)
        if any(not isinstance(c, list) or not c or any(not isinstance(x, str) or not x or "\0" in x for x in c) for c in checks):
            raise ValueError("Comandos de aceitação devem ser listas de argumentos.")
        metadata.append(dict(id=identifier, category=task["category"],
                             project_sha256=digest(str(project).encode()), commit=commit,
                             prompts_sha256=hashes, acceptance_sha256=digest(encoded(checks))))
    if len({t["project_sha256"] for t in metadata}) < protocol["minimum_projects"]:
        raise ValueError("São necessários pelo menos dois projetos autorizados.")
    all_prompts = [h for task in metadata for h in task["prompts_sha256"]]
    if len(all_prompts) != len(set(all_prompts)):
        raise ValueError("A amostra deve conter prompts distintos.")
    return dict(protocol=protocol["id"], protocol_sha256=digest(PROTOCOL.read_bytes()),
                protocol_text_sha256=digest(PROTOCOL.with_suffix(".md").read_bytes()),
                manifest_sha256=digest(raw), source_sha256=sources_hash(), tasks=metadata)


def call(report, output, command, project, env, binary, *, case, arm, repetition,
         turn, choice, previous=None, telemetry=None, expected_session=None,
         timeout=180, expected_classifications=None, state_dir=None):
    """Persist the attempt BEFORE spawn; unknown consumption survives crashes."""
    before = provenance(binary)
    source_before = sources_hash()
    row = dict(case=case, arm=arm, repetition=repetition, turn=turn,
               requested_model=choice, session_id=expected_session, status="started",
               execution_ok=False, model_confirmed=False, functional_passed=None,
               human_review="pending", critical_regression=None,
               cli_estimated_cost_usd=None, total_tokens=None, duration_seconds=0,
               client_before=before, client_after=None, source_before_sha256=source_before)
    report["records"].append(row)
    save(output, report)
    started = time.monotonic()
    try:
        code, text = execute(command, project, env, timeout=timeout)
    except KeyboardInterrupt:
        row["duration_seconds"] = time.monotonic() - started
        row["status"] = "interrupted"
        save(output, report)
        raise
    row["duration_seconds"] = time.monotonic() - started
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            payload = {}
    except (ValueError, TypeError):
        payload = {}
    current = snapshot(payload)
    row.update(marginal(current, previous, resumed=turn > 1))
    row.update(status="finished", exit_code=code, client_after=provenance(binary),
               session_id=current["session_id"],
               execution_ok=code == 0 and payload.get("subtype") == "success" and not payload.get("is_error"))
    row["source_after_sha256"] = sources_hash()
    expected_sources = report.get("lock", {}).get("source_sha256", report.get("source_sha256"))
    if row["source_after_sha256"] != source_before or expected_sources and source_before != expected_sources:
        row["measurement_issues"].append("router_or_harness_sources_changed")
    if expected_session and current["session_id"] != expected_session:
        row["measurement_issues"].append("unexpected_session")
    if not stable(before, row["client_after"]):
        row["measurement_issues"].append("client_changed_or_unverified")
    if telemetry is not None:
        try:
            observed = json.loads(telemetry.read_bytes())
        except (OSError, ValueError):
            observed = {}
        # Instrumentation output has an explicit numeric allowlist.
        row["router_observation"] = {key: observed.get(key) for key in (
            "classifications", "classification_seconds", "native_seconds", "router_seconds")}
        counts = row["router_observation"]
        if (type(counts["classifications"]) is not int or counts["classifications"] != expected_classifications
                or any(type(counts[k]) not in (int, float) or not 0 <= counts[k] < 86400
                       for k in counts if k != "classifications")):
            row["measurement_issues"].append("invalid_router_observation")
    if state_dir is not None:
        try:
            task = Store(state_dir).get("latest", project)
            row["persisted_session_confirmed"] = task["id"] == current["session_id"] and task["launches"] == turn
            if choice is None:
                choice = task["model"]
                row["requested_model"] = choice
        except (OSError, ValueError):
            row["persisted_session_confirmed"] = False
        if not row["persisted_session_confirmed"]:
            row["measurement_issues"].append("router_session_not_confirmed")
    row["model_confirmed"] = bool(choice and row["effective_models"]) and all(
        matches_choice(choice, m) for m in row["effective_models"])
    save(output, report)
    return current, payload.get("result", "")


def summarize(report, reviews=None):
    rows = report["records"]
    reviews = reviews or {}
    planned = report["planned_calls"]
    identities = {encoded(r.get("client_before")) for r in rows}
    choices = {}
    for row in rows:
        choices.setdefault(row["requested_model"], set()).update(row.get("effective_models", []))
    model_stable = all(len(models) == 1 for models in choices.values())
    tasks = report.get("lock", {}).get("tasks", [])
    expected = {(t["id"], repetition, arm, turn) for t in tasks
                for repetition in range(1, report.get("repetitions", 1) + 1)
                for arm in ("baseline", "routed") for turn in (1, 2)}
    observed = [(r["case"], r["repetition"], r["arm"], r["turn"]) for r in rows]
    design_complete = bool(expected) and set(observed) == expected and len(observed) == len(set(observed))
    comparable = (len(rows) == planned and bool(rows) and len(identities) == 1
                  and model_stable and design_complete and not report.get("stopped")
                  and all(stable(r.get("client_before"), r.get("client_after"))
                          and not r.get("measurement_issues") and r.get("cli_estimated_cost_usd") is not None
                          and r.get("total_tokens") is not None and r.get("model_confirmed") for r in rows))
    quality = comparable and all(r["execution_ok"] and r["functional_passed"] is True for r in rows)
    human_pass = all(reviews.get(f'{r["case"]}:{r["repetition"]}:{r["arm"]}:{r["turn"]}') ==
                     dict(verdict="pass", critical_regression=False) for r in rows) and bool(rows)
    totals = {}
    for arm in ("baseline", "routed"):
        selected = [r for r in rows if r["arm"] == arm]
        totals[arm] = dict(calls=len(selected), failures=sum(not r["execution_ok"] for r in selected),
                           functional_passed=sum(r["functional_passed"] is True for r in selected),
                           known_cost_usd=sum(r["cli_estimated_cost_usd"] or 0 for r in selected),
                           cost_complete=bool(selected) and all(r["cli_estimated_cost_usd"] is not None for r in selected),
                           known_tokens=sum(r["total_tokens"] or 0 for r in selected),
                           tokens_complete=bool(selected) and all(r["total_tokens"] is not None for r in selected),
                           seconds=sum(r["duration_seconds"] for r in selected))
        totals[arm]["by_turn"] = {str(turn): dict(
            known_cost_usd=sum(r["cli_estimated_cost_usd"] or 0 for r in selected if r["turn"] == turn),
            known_tokens=sum(r["total_tokens"] or 0 for r in selected if r["turn"] == turn),
            seconds=sum(r["duration_seconds"] for r in selected if r["turn"] == turn)) for turn in (1, 2)}
    reductions = {}
    for metric, key in (("cost_usd", "known_cost_usd"), ("tokens", "known_tokens"), ("seconds", "seconds")):
        base, routed = totals["baseline"][key], totals["routed"][key]
        reductions[metric] = 100 * (base - routed) / base if quality and human_pass and base else None
    verdict = "inconclusive"
    failed_review = any(v.get("verdict") == "fail" or v.get("critical_regression") is True for v in reviews.values())
    if failed_review or any(r["functional_passed"] is False for r in rows):
        verdict = "failed_quality"
    elif quality and human_pass:
        verdict = "observed_sample_reduction" if all(v is not None and v > 0 for v in reductions.values()) else "not_all_metrics_reduced"
    return dict(verdict=verdict, comparable=comparable, functional_quality_passed=quality,
                human_review_passed=human_pass, totals=totals, observed_reduction_percent=reductions,
                api_invoice_usd=None, subscription_quota=None, general_savings_proven=False)


def flags(protocol):
    # No Agent/Task/MCP/web tools: inference delegation is outside this study.
    return ["-p", "--output-format", "json", "--no-chrome", "--restricted",
            "--tools", "Read,Edit,Write,Glob,Grep,Bash", "--permission-mode", "acceptEdits",
            "--effort", protocol["effort"], "--max-turns", str(protocol["max_turns_per_call"]),
            "--max-budget-usd", str(protocol["max_cost_per_call_usd"])]


def run(manifest, lock, protocol, binary, output, work_root):
    private_directory(work_root)
    manifest_raw = manifest.read_bytes()
    if digest(manifest_raw) != lock["manifest_sha256"]:
        raise ValueError("O manifesto mudou desde o congelamento.")
    data = json.loads(manifest_raw)
    # Copy the authorized bytes once. Native/model activity and external edits
    # cannot replace a later turn's prompt after the lock was verified.
    for task, metadata in zip(data["tasks"], lock["tasks"]):
        frozen_prompts = []
        for turn, source in enumerate(task["prompts"]):
            raw = Path(source).read_bytes()
            if digest(raw) != metadata["prompts_sha256"][turn]:
                raise ValueError("Um prompt mudou desde o congelamento.")
            destination = work_root / f'{task["id"]}-prompt-{turn+1}.txt'
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            frozen_prompts.append(str(destination))
        task["prompts"] = frozen_prompts
    report = dict(protocol=protocol["id"], lock_sha256=digest(encoded(lock)), lock=lock,
                  python=platform.python_version(), platform=platform.system(),
                  load_average=list(os.getloadavg()), planned_calls=len(data["tasks"]) * 2 * protocol["repetitions"] * 2,
                  repetitions=protocol["repetitions"],
                  max_estimated_cost_usd=protocol["max_cost_usd"], records=[], stopped=None)
    config = work_root / "config.json"
    save(config, Config().snapshot())
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    save(output, report)
    try:
        for repetition in range(1, protocol["repetitions"] + 1):
            for index, task in enumerate(data["tasks"]):
                order = ("baseline", "routed") if (index + repetition - 1) % 2 == 0 else ("routed", "baseline")
                for arm in order:
                    local = work_root / f'{task["id"]}-{repetition}-{arm}'
                    private_directory(local)
                    archive = local / "snapshot.tar"
                    with archive.open("xb") as stream:
                        subprocess.run(["git", "-C", task["project"], "archive", task["commit"]], stdout=stream, check=True)
                    project = local / "project"
                    private_directory(project)
                    with tarfile.open(archive) as stream:
                        stream.extractall(project, filter="data")
                    archive.unlink()
                    previous = None
                    session = str(uuid.uuid4()) if arm == "baseline" else None
                    choice = protocol["baseline"] if arm == "baseline" else None
                    for turn, source in enumerate(task["prompts"], 1):
                        spent = sum(r["cli_estimated_cost_usd"] or 0 for r in report["records"])
                        if spent + protocol["max_cost_per_call_usd"] > protocol["max_cost_usd"]:
                            report["stopped"] = "budget_headroom_exhausted"
                            return report
                        prompt = Path(source).read_text(encoding="utf-8")
                        telemetry = None
                        if arm == "baseline":
                            command = [binary, "--model", choice, "--session-id" if turn == 1 else "--resume", session,
                                       *flags(protocol), "--", prompt]
                        else:
                            telemetry = local / f"telemetry-{turn}.json"
                            command = [sys.executable, str(ROOT / "evaluation/observe_router.py"), str(telemetry),
                                       "--claude-bin", binary, "--state-dir", str(local / "state"), "--config", str(config)]
                            if turn == 1:
                                command += ["new", "--prompt-file", source, "--cwd", str(project)]
                            else:
                                command += ["resume", session, "--prompt-file", source]
                            command += ["--timeout", str(protocol["timeout_seconds"] - 10), "--", *flags(protocol)]
                        current, _ = call(report, output, command, project, env, binary,
                                          case=task["id"], arm=arm, repetition=repetition, turn=turn,
                                          choice=choice, previous=previous, telemetry=telemetry,
                                          expected_session=session, timeout=protocol["timeout_seconds"],
                                          expected_classifications=1 if turn == 1 else 0,
                                          state_dir=local / "state" if arm == "routed" else None)
                        row = report["records"][-1]
                        choice = row["requested_model"]
                        session = current["session_id"]
                        previous = current
                        if not row["execution_ok"] or row["measurement_issues"] or not row["model_confirmed"]:
                            report["stopped"] = "execution_or_measurement_failure"
                            return report
                        if row["cli_estimated_cost_usd"] > protocol["max_cost_per_call_usd"]:
                            report["stopped"] = "native_budget_overshoot"
                            return report
                        code, _ = execute(task["acceptance"][turn - 1], project, env, timeout=protocol["timeout_seconds"])
                        row["functional_passed"] = code == 0
                        row["acceptance_exit_code"] = code
                        save(output, report)
    except KeyboardInterrupt:
        report["stopped"] = "interrupted"
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError):
        report["stopped"] = "local_setup_failure"
    finally:
        report["summary"] = summarize(report)
        save(output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--report", type=Path, help="Recalcular relatório existente sem inferência")
    parser.add_argument("--reviews", type=Path, help="Revisão humana ligada ao hash do relatório")
    args = parser.parse_args(argv)
    protocol = json.loads(PROTOCOL.read_bytes())
    try:
        if args.report:
            if args.real or args.freeze or args.manifest:
                parser.error("--report não pode executar nem congelar uma coorte.")
            raw = args.report.read_bytes()
            report = json.loads(raw)
            reviews = {}
            if args.reviews:
                review = json.loads(args.reviews.read_bytes())
                if review.get("report_sha256") != digest(raw) or review.get("reviewed_by_human") is not True:
                    parser.error("Revisão humana deve identificar o hash exato do relatório.")
                reviews = review["records"]
                keys = {f'{r["case"]}:{r["repetition"]}:{r["arm"]}:{r["turn"]}' for r in report["records"]}
                if not isinstance(reviews, dict) or set(reviews) - keys or any(
                    not isinstance(v, dict) or set(v) != {"verdict", "critical_regression"}
                    or v["verdict"] not in {"pass", "fail", "pending"}
                    or v["critical_regression"] is not None and type(v["critical_regression"]) is not bool
                    for v in reviews.values()):
                    parser.error("Revisões devem conter somente chaves de turnos existentes e veredictos válidos.")
            result = dict(report_sha256=digest(raw), summary=summarize(report, reviews))
            if args.output:
                if args.output.exists():
                    parser.error("--output deve ser novo.")
                save(args.output, result)
            print(json.dumps(result, indent=2))
            return 0
        if not args.manifest:
            if args.freeze or args.real:
                parser.error("--manifest é obrigatório para congelar ou executar.")
            print(json.dumps(dict(protocol=protocol, status="awaiting_authorized_private_tasks",
                                  protocol_sha256=digest(PROTOCOL.read_bytes())), indent=2))
            return 0
        lock = freeze(args.manifest, protocol)
        if args.freeze:
            if args.real or not args.lock or args.lock.exists():
                parser.error("--freeze exige --lock novo, sem --real.")
            save(args.lock, lock)
        elif args.real:
            if not args.lock or json.loads(args.lock.read_bytes()) != lock:
                parser.error("O lock deve corresponder ao manifesto, protocolo e fontes atuais.")
            if args.max_cost_usd != protocol["max_cost_usd"]:
                parser.error("Autorize explicitamente o teto congelado com --max-cost-usd.")
            if not args.output or args.output.exists() or not args.output.parent.is_dir():
                parser.error("--output deve ser novo em diretório existente.")
            if not args.work_dir or args.work_dir.exists() or args.work_dir.resolve().is_relative_to(ROOT):
                parser.error("--work-dir deve ser novo e ficar fora do repositório do roteador.")
            report = run(args.manifest, lock, protocol, executable(args.claude_bin), args.output, args.work_dir)
            print(json.dumps(report["summary"], indent=2))
            return 0 if report["summary"]["verdict"] == "observed_sample_reduction" else 1
        print(json.dumps(lock, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        # Do not echo private paths/commands/manifest values in public logs.
        parser.error("Manifesto inválido ou snapshot indisponível; confira o protocolo e os arquivos locais.")


if __name__ == "__main__":
    raise SystemExit(main())
