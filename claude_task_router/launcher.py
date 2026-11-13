"""Native Claude CLI adapter. No shell, proxy, SDK or prompt instructions."""

import json
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys

from .config import validate_model
from .state import launch_model, matches_choice

MINIMUM_VERSION = (2, 1, 251)
VALUE_FLAGS = {
    "--output-format", "--permission-mode", "--max-turns", "--max-budget-usd",
    "--tools", "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools",
    "--effort", "--append-system-prompt", "--json-schema", "--name", "-n",
}
SWITCH_FLAGS = {
    "--print", "-p", "--verbose", "--include-partial-messages", "--include-hook-events",
    "--dangerously-skip-permissions", "--no-chrome",
}


def validate_extra(args: list[str]) -> list[str]:
    """Allow only flags that do not replace task/session/model/hook ownership."""
    index = 0
    while index < len(args):
        token = args[index]
        key, equals, value = token.partition("=")
        if key in SWITCH_FLAGS and not equals:
            index += 1
        elif key in VALUE_FLAGS:
            if not equals:
                index += 1
                if index >= len(args) or args[index].startswith("-"):
                    raise ValueError(f"Falta valor para {key}.")
            elif not value:
                raise ValueError(f"Falta valor para {key}.")
            index += 1
        else:
            raise ValueError(f"Argumento Claude não suportado: {key}. Use ctr --help.")
    if any(x.split("=")[0] in {"--output-format", "--max-budget-usd", "--max-turns",
                               "--include-partial-messages", "--include-hook-events", "--json-schema"}
           for x in args) and not any(x in {"-p", "--print"} for x in args):
        raise ValueError("Opções de saída/limite exigem -- -p (modo print).")
    return args


def executable(binary: str) -> str:
    resolved = shutil.which(binary)
    if not resolved:
        raise ValueError(f"Claude Code não encontrado: {binary}. Instale-o ou use --claude-bin.")
    return str(Path(resolved).absolute())


def hook_settings(state_dir: Path) -> str:
    command = shlex.join([sys.executable, str(Path(__file__).with_name("hook.py").resolve()),
                          "--state-dir", str(state_dir)])
    return json.dumps({"switchModelsOnFlag": False, "hooks": {
        event: [{"hooks": [{"type": "command", "command": command, "timeout": 5}]}]
        for event in ("SessionStart", "PostModelSwitch")
    }}, separators=(",", ":"))


def build_command(binary: str, task: dict, state_dir: Path, prompt: str | None,
                  extra: list[str], resume: bool) -> list[str]:
    validate_extra(extra)
    model = validate_model(launch_model(task))
    command = [binary, "--model", model,
               "--resume" if resume else "--session-id", task["id"],
               "--settings", hook_settings(state_dir), *extra]
    if prompt is not None:
        # Prevent leading dashes in user text from becoming Claude CLI flags.
        command.extend(["--", prompt])
    return command


def run(store, task: dict, binary: str, prompt: str | None, extra: list[str], resume: bool) -> int:
    cwd = Path(task["cwd"])
    if not cwd.is_dir():
        raise ValueError(f"Diretório original não existe: {cwd}")
    command = build_command(binary, task, store.root, prompt, extra, resume)
    print(f"[ctr] tarefa={task['id']} solicitado={task['model']} modelo={launch_model(task)} "
          f"{'retomada' if resume else 'nova'}", file=sys.stderr)
    # Inherit terminal and environment; Claude retains its own auth and permissions.
    child = subprocess.Popen(command, cwd=cwd)
    handlers = {}
    def forward(signum, _frame):
        if child.poll() is None:
            child.send_signal(signum)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        handlers[signum] = signal.signal(signum, forward)
    try:
        store.launched(task["id"])
        while True:
            try:
                result = child.wait()
                break
            except KeyboardInterrupt:
                # Terminal SIGINT already reaches Claude. Keep supervising it so a
                # second launcher cannot acquire the lock while it is still alive.
                continue
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait()
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
    code = result if result >= 0 else 128 - result
    store.finished(task["id"], code)
    try:
        store.reconcile_transcript(task["id"])
    except (OSError, ValueError):
        pass
    current = store.get(task["id"])
    if not current["observed_at"]:
        print("[ctr] modelo efetivo não observado; escolha salva preservada. "
              "Use ID explícito ou ctr model para fixar a versão.", file=sys.stderr)
    elif not matches_choice(launch_model(current), current["effective_model"]):
        print(f"[ctr] divergência: solicitado={current['model']} "
              f"efetivo={current['effective_model']}; escolha salva preservada.", file=sys.stderr)
    return code


def doctor(binary: str) -> tuple[dict, int]:
    resolved = executable(binary)
    version = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=15)
    help_result = subprocess.run([resolved, "--help"], capture_output=True, text=True, timeout=15)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", version.stdout)
    actual = tuple(map(int, match.groups())) if match else None
    required = ("--model", "--session-id", "--resume", "--settings")
    missing = [flag for flag in required if flag not in help_result.stdout]
    ok = version.returncode == help_result.returncode == 0 and actual is not None and actual >= MINIMUM_VERSION and not missing
    return dict(ok=ok, executable=resolved, version=version.stdout.strip(),
                minimum_version="2.1.251", missing_flags=missing,
                note="Verificação local; não testa acesso aos modelos nem hooks desativados por política."), 0 if ok else 1
