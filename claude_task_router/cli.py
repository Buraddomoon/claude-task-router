"""Small task lifecycle CLI. Routing only occurs in new/classify."""

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from . import __version__
from .boundary import choose
from .classifier import Decision, classify, validate_prompt
from .config import MAX_PROMPT_BYTES, TIERS, load_config, validate_model
from .launcher import doctor, executable, run, validate_extra, validate_timeout
from .state import Store, default_state_dir, launch_model


def parser():
    p = argparse.ArgumentParser(description="Roteamento local por tarefa para Claude Code.",
        epilog="Opções globais vêm antes do comando. Opções Claude permitidas após --: "
               "-p, --output-format, --permission-mode, --max-budget-usd, --max-turns, "
               "--effort, --tools, --allowedTools, --disallowedTools, --name, --verbose, "
               "--append-system-prompt, --json-schema, --include-partial-messages, "
               "--include-hook-events, --no-chrome, --dangerously-skip-permissions.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--state-dir", type=Path, default=None)
    p.add_argument("--config", type=Path, default=None, help="JSON explícito, usado somente em new/classify")
    p.add_argument("--claude-bin", default="claude")
    subs = p.add_subparsers(dest="command", required=True)
    for name in ("new", "classify", "run"):
        sub = subs.add_parser(name, help={"new": "Nova tarefa", "classify": "Explicar decisão sem executar Claude",
                                        "run": "Detectar tarefa nova ou continuação localmente"}[name])
        sub.add_argument("prompt", nargs="?", help="Texto inicial; sem texto, lê uma linha no terminal")
        sub.add_argument("--prompt-file", type=Path, help="Arquivo UTF-8; - lê stdin")
        sub.add_argument("--cwd", type=Path, default=Path.cwd())
        manual = sub.add_mutually_exclusive_group()
        manual.add_argument("--model", help="Ignora classificação e fixa este modelo")
        manual.add_argument("--tier", choices=TIERS)
        if name in {"new", "run"}:
            sub.add_argument("--dry-run", action="store_true", help="Planejar sem persistir ou executar")
            sub.add_argument("--timeout", type=float, help="Tempo limite do launcher em segundos; exige modo print")
        else:
            sub.add_argument("--json", action="store_true")
        if name == "run":
            boundary = sub.add_mutually_exclusive_group()
            boundary.add_argument("--new", dest="mode", action="store_const", const="new")
            boundary.add_argument("--continue", dest="mode", action="store_const", const="continue")
            sub.set_defaults(mode="auto")
    resume = subs.add_parser("resume", help="Retomar tarefa sem reclassificar")
    resume.add_argument("task", nargs="?", default="latest")
    resume.add_argument("prompt", nargs="?")
    resume.add_argument("--prompt-file", type=Path)
    resume.add_argument("--model")
    resume.add_argument("--dry-run", action="store_true")
    resume.add_argument("--timeout", type=float)
    recover = subs.add_parser("recover", help="Abrir sessão substituta com a escolha salva, sem histórico")
    recover.add_argument("task")
    recover.add_argument("prompt", nargs="?", help="Contexto para a nova sessão; não reenvia a conversa anterior")
    recover.add_argument("--prompt-file", type=Path)
    recover.add_argument("--cwd", type=Path, help="Diretório substituto; padrão: projeto original")
    recover.add_argument("--dry-run", action="store_true")
    recover.add_argument("--timeout", type=float)
    model = subs.add_parser("model", help="Fixar modelo de uma tarefa inativa")
    model.add_argument("task")
    model.add_argument("model")
    status = subs.add_parser("status", help="Listar tarefas (diretório atual por padrão)")
    status.add_argument("--all", action="store_true")
    status.add_argument("--json", action="store_true")
    show = subs.add_parser("show", help="Metadados e eventos de uma tarefa")
    show.add_argument("task", nargs="?", default="latest")
    subs.add_parser("doctor", help="Verificar interface instalada sem chamada de IA")
    models = subs.add_parser("models", help="Consultar modelos pela interface nativa pública")
    inspection = models.add_mutually_exclusive_group()
    inspection.add_argument("--check", metavar="MODELO", help="Validar nome/restrição pelo comando nativo, sem turno de IA")
    inspection.add_argument("--probe", metavar="MODELO", help="Teste real curto com consumo explícito de IA")
    return p


def read_prompt(args, required: bool) -> str | None:
    if args.prompt is not None and args.prompt_file is not None:
        raise ValueError("Use prompt ou --prompt-file, não ambos.")
    prompt = args.prompt
    if args.prompt_file is not None:
        if str(args.prompt_file) == "-":
            raw = sys.stdin.buffer.read(MAX_PROMPT_BYTES + 1)
        else:
            with args.prompt_file.open("rb") as stream:
                raw = stream.read(MAX_PROMPT_BYTES + 1)
        if len(raw) > MAX_PROMPT_BYTES:
            raise ValueError("Prompt excede o limite; use referências a arquivos.")
        prompt = raw.decode("utf-8")
    elif prompt is None and required:
        if sys.stdin.isatty():
            prompt = input("Tarefa: ")
        else:
            raise ValueError("Informe a tarefa ou use --prompt-file - para stdin.")
    if prompt is not None:
        validate_prompt(prompt)
        # Linux limits an individual argv string to 128 KiB, even with a large ARG_MAX.
        if len(prompt.encode("utf-8")) > 96 * 1024:
            raise ValueError("Launcher aceita até 96 KiB por prompt; use referências a arquivos.")
    return prompt


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        separator = argv.index("--")
        argv, extra = argv[:separator], argv[separator + 1:]
    # A bare ctr opens the most recent project task. Explicit commands retain
    # their existing grammar; a single quoted prompt is shorthand for run.
    commands = {"new", "classify", "run", "resume", "recover", "model", "models", "status", "show", "doctor"}
    index = 0
    while index < len(argv) and argv[index].split("=", 1)[0] in {"--state-dir", "--config", "--claude-bin"}:
        index += 1 if "=" in argv[index] else 2
    if index == len(argv) or (index < len(argv) and not argv[index].startswith("-")
                             and argv[index] not in commands and any(c.isspace() for c in argv[index])):
        argv.insert(index, "run")
    args = parser().parse_args(argv)
    try:
        validate_extra(extra)
        validate_timeout(extra, getattr(args, "timeout", None))
        if extra and args.command not in {"new", "resume", "recover", "run"}:
            raise ValueError("Argumentos Claude são aceitos somente em new/resume/recover.")
        if args.command == "run":
            prompt = read_prompt(args, required=False)
            cwd = args.cwd.expanduser().resolve()
            if not cwd.is_dir():
                raise ValueError(f"Diretório não existe: {cwd}")
            root = args.state_dir or default_state_dir()
            latest = None
            if (root.expanduser() / "tasks.sqlite3").exists():
                current_store = Store(args.state_dir)
                candidates = current_store.list_tasks(cwd, limit=1)
                latest = current_store.get(candidates[0]["id"]) if candidates else None
            action, reason = choose(prompt, latest, args.mode)
            print(f"[ctr] {action}: {reason}; use --new/--continue para escolher explicitamente.", file=sys.stderr)
            if action == "resume":
                if args.tier:
                    raise ValueError("--tier só se aplica a tarefa nova; use --new ou --model.")
                args.command, args.task, args.prompt, args.prompt_file = "resume", latest["id"], prompt, None
            else:
                args.command, args.prompt, args.prompt_file = "new", prompt, None
        if args.command == "doctor":
            result, code = doctor(args.claude_bin)
            dump(result)
            return code
        if args.command == "models":
            from .models import inspect_model
            result, code = inspect_model(args.claude_bin, args.check or args.probe, probe=bool(args.probe))
            dump(result)
            return code
        if args.command in {"new", "classify"}:
            config = load_config(args.config)
            prompt = read_prompt(args, required=True)
            cwd = args.cwd.expanduser().resolve()
            if not cwd.is_dir():
                raise ValueError(f"Diretório não existe: {cwd}")
            if args.model:
                decision = Decision("manual", validate_model(args.model), 0,
                                    ("manual_model",), 0, len(prompt), "manual")
            elif args.tier:
                decision = Decision(args.tier, config.models[args.tier], 0,
                                    ("manual_tier",), 0, len(prompt), "manual")
            else:
                decision = classify(prompt, config)
            if args.command == "classify":
                if args.json:
                    dump(decision.to_dict())
                else:
                    print(f"{decision.tier} → {decision.model} ({', '.join(decision.reasons)})")
                return 0
            if args.dry_run:
                dump(dict(decision=decision.to_dict(), cwd=str(cwd), persisted=False))
                return 0
            binary = executable(args.claude_bin)
            store = Store(args.state_dir)
            task = store.create(cwd, prompt, decision.to_dict(), config.snapshot())
            with store.task_lock(task["id"]):
                return run(store, task, binary, prompt, extra, resume=False, timeout=args.timeout)
        store = Store(args.state_dir)
        if args.command == "status":
            tasks = store.list_tasks(Path.cwd(), all_projects=args.all)
            if args.json:
                dump(tasks)
            else:
                for task in tasks:
                    print(f"{task['id']}  solicitado={task['model']}  "
                          f"efetivo={task['effective_model'] or 'não observado'}  {task['cwd']}")
                if not tasks:
                    print("Nenhuma tarefa neste diretório.")
            return 0
        task = store.get(args.task)
        if args.command == "show":
            task["events"] = store.events(task["id"])
            dump(task)
            return 0
        if args.command == "model":
            model = validate_model(args.model)
            with store.task_lock(task["id"]):
                store.set_model(task["id"], model)
            print(f"{task['id']} → {model}")
            return 0
        if args.command == "recover":
            prompt = read_prompt(args, required=True)
            cwd = (args.cwd or Path(task["cwd"])).expanduser().resolve()
            if not cwd.is_dir():
                raise ValueError(f"Diretório não existe: {cwd}. Use recover --cwd com um diretório válido.")
            if args.dry_run:
                dump(dict(recovered_from=task["id"], cwd=str(cwd), model=launch_model(task),
                          reclassified=False, persisted=False, new_session=True))
                return 0
            binary = executable(args.claude_bin)
            with store.task_lock(task["id"]):
                replacement = store.recover(task["id"], cwd, prompt)
            print(f"[ctr] recuperação de {task['id']} → {replacement['id']}; "
                  "nova sessão sem histórico anterior, escolha salva preservada.", file=sys.stderr)
            with store.task_lock(replacement["id"]):
                return run(store, replacement, binary, prompt, extra, resume=False, timeout=args.timeout)
        if args.command == "resume":
            prompt = read_prompt(args, required=False)
            if args.model:
                validate_model(args.model)
            if args.dry_run:
                dump(dict(task=task["id"], cwd=task["cwd"], model=args.model or launch_model(task),
                          reclassified=False, persisted=False))
                return 0
            binary = executable(args.claude_bin)
            with store.task_lock(task["id"]):
                if args.model:
                    store.set_model(task["id"], args.model, source="resume_override")
                task = store.get(task["id"])
                return run(store, task, binary, prompt, extra, resume=True, timeout=args.timeout)
        raise ValueError("Comando desconhecido.")
    except (ValueError, TypeError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"ctr: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
