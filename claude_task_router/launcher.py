"""Native Claude CLI adapter. No shell, proxy, SDK or prompt instructions."""

import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

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
    "--dangerously-skip-permissions", "--no-chrome", "--restricted",
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


def hook_settings(state_dir: Path, execution_id: str) -> str:
    command = shlex.join([sys.executable, str(Path(__file__).with_name("hook.py").resolve()),
                          "--state-dir", str(state_dir), "--execution-id", execution_id])
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
               "--settings", hook_settings(state_dir, task["execution_id"]), *extra]
    if prompt is not None:
        # Prevent leading dashes in user text from becoming Claude CLI flags.
        command.extend(["--", prompt])
    return command


def validate_timeout(extra, timeout):
    if timeout is not None and (not math.isfinite(timeout) or not 0 < timeout <= 86400
                                or not any(x in {"-p", "--print"} for x in extra)):
        raise ValueError("--timeout deve estar entre 0 e 86400 segundos e exige -- -p.")


def run(store, task: dict, binary: str, prompt: str | None, extra: list[str], resume: bool,
        timeout: float | None = None) -> int:
    cwd = Path(task["cwd"])
    if not cwd.is_dir():
        raise ValueError(f"Diretório original não existe: {cwd}. Restaure-o ou use "
                         f"ctr recover {task['id']} --cwd /diretorio/valido --prompt-file tarefa.txt.")
    validate_extra(extra)
    validate_timeout(extra, timeout)
    store.launched(task["id"])
    task = store.get(task["id"])
    command = build_command(binary, task, store.root, prompt, extra, resume)
    print(f"[ctr] tarefa={task['id']} solicitado={task['model']} modelo={launch_model(task)} "
          f"{'retomada' if resume else 'nova'}", file=sys.stderr)
    # Inherit terminal and environment; Claude retains its own auth and permissions.
    try:
        print_mode = any(x in {"-p", "--print"} for x in extra)
        child = subprocess.Popen(command, cwd=cwd, start_new_session=print_mode)
    except OSError as exc:
        store.finished(task["id"], 2)
        raise ValueError(f"Não foi possível iniciar Claude: {exc}. Tarefa {task['id']} preservada; "
                         "corrija o executável e use ctr resume, ou ctr recover se não houver sessão.") from exc
    handlers = {}
    deadline = time.monotonic() + timeout if timeout is not None else None
    timed_out = False

    def send(signum):
        try:
            if print_mode:
                os.killpg(child.pid, signum)
            else:
                child.send_signal(signum)
        except ProcessLookupError:
            pass

    def forward(signum, _frame):
        if child.poll() is None:
            send(signum)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        handlers[signum] = signal.signal(signum, forward)
    try:
        while True:
            try:
                remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
                result = child.wait(timeout=remaining)
                break
            except subprocess.TimeoutExpired:
                timed_out = True
                send(signal.SIGTERM)
                try:
                    result = child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    send(signal.SIGKILL)
                    result = child.wait()
                break
            except KeyboardInterrupt:
                # Terminal SIGINT already reaches Claude. Keep supervising it so a
                # second launcher cannot acquire the lock while it is still alive.
                if print_mode:
                    send(signal.SIGINT)
                continue
    finally:
        if child.poll() is None:
            send(signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                send(signal.SIGKILL)
                child.wait()
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
    code = 124 if timed_out else result if result >= 0 else 128 - result
    if timed_out:
        print("[ctr] Tempo limite excedido; grupo do cliente print encerrado, sem repetição automática.", file=sys.stderr)
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
    if code:
        print(f"[ctr] {'Retomada' if resume else 'Execução'} falhou ou foi interrompida "
              f"(código {code}); tarefa {task['id']} preservada. Confira o erro do Claude. "
              f"Tente ctr resume {task['id']}; se a sessão não existir, use "
              f"ctr recover {task['id']} --prompt-file tarefa.txt para abrir outra sessão "
              "com a mesma escolha. Nenhuma repetição automática foi feita.", file=sys.stderr)
    return code


def doctor(binary: str) -> tuple[dict, int]:
    resolved = executable(binary)
    version = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=15)
    help_result = subprocess.run([resolved, "--help"], capture_output=True, text=True, timeout=15)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", version.stdout)
    actual = tuple(map(int, match.groups())) if match else None
    required = ("--model", "--session-id", "--resume", "--settings")
    missing = [flag for flag in required if flag not in help_result.stdout]
    authentication = dict(logged_in=None, method=None, provider=None)
    try:
        auth = subprocess.run([resolved, "auth", "status"], capture_output=True, text=True, timeout=15)
        data = json.loads(auth.stdout)
        if isinstance(data, dict) and type(data.get("loggedIn")) is bool:
            authentication = dict(logged_in=data["loggedIn"],
                                  method=data.get("authMethod") if data.get("authMethod") in
                                  {"none", "claude.ai", "oauth_token", "api_key", "api_key_helper", "third_party", "simulated"} else None,
                                  provider=data.get("apiProvider") if data.get("apiProvider") in
                                  {"firstParty", "bedrock", "vertex", "foundry"} else None)
    except (ValueError, OSError, subprocess.SubprocessError):
        pass
    ok = (version.returncode == help_result.returncode == 0 and actual is not None
          and actual >= MINIMUM_VERSION and not missing and authentication["logged_in"] is True)
    return dict(ok=ok, executable=resolved, version=version.stdout.strip(),
                minimum_version="2.1.251", missing_flags=missing, authentication=authentication,
                note="Verificação local; não testa acesso aos modelos nem hooks desativados por política."), 0 if ok else 1
