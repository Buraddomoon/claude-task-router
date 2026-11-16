"""Bounded local prompt gate for supervised native CLI sessions.

The socket transports prompts only in memory. It never writes a transcript or
asks a model to classify. The native client keeps ownership of the terminal.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import socket
import tempfile
import time

from .classifier import normalize, validate_prompt
from .topics import TaskContext, contextual_action

MAX_MESSAGE = 1024 * 1024
NEW = re.compile(
    r"^(?:nova tarefa|novo assunto|outra tarefa|outro assunto|new task|new topic|"
    r"switching topics)\s*:\s*(\S.*)$", re.S)


def boundary(prompt):
    """Only an explicit, unquoted, non-negated boundary can replace a process."""
    text = normalize(prompt.strip())
    match = NEW.fullmatch(text)
    if not match:
        return False
    body = match.group(1)
    # Quoted examples, questions and denials must not cause a handoff.
    return not re.match(r"(?:nao\b|nunca\b|not\b|no\b|do not\b|don't\b|"
                        r"don’t\b|never\b|talvez\b|maybe\b|[\"'`?])", body)


def detect(prompt, context=None):
    if boundary(prompt):
        return "new"
    return contextual_action(prompt, context)


@dataclass
class Handoff:
    prompt: str
    action: str = "new"


CONTROL = re.compile(r"^ctr:(new|continue|cancel)\s+([a-f0-9]{6})$")


class PromptGate:
    def __init__(self, task, initial_prompt, context=None):
        self.task = task
        self.initial_hash = (hashlib.sha256(initial_prompt.encode()).digest()
                             if initial_prompt is not None else None)
        self.token = secrets.token_hex(32)
        self.context = context or TaskContext.from_prompt(initial_prompt)
        self.proposal = None
        self.directory = tempfile.TemporaryDirectory(prefix="ctr-gate-", dir="/tmp")
        # Short path also works on macOS, whose Unix socket path limit is 104 bytes.
        self.path = str(Path(self.directory.name) / "control.sock")
        self.server = socket.socket(socket.AF_UNIX)
        try:
            self.server.bind(self.path)
            self.server.listen(4)
            self.server.setblocking(False)
        except BaseException:
            self.close()
            raise
        self.peer = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if getattr(self, "peer", None):
            self.peer.close()
        self.server.close()
        self.directory.cleanup()

    def poll(self):
        try:
            peer, _ = self.server.accept()
        except BlockingIOError:
            return None
        peer.settimeout(0.5)
        keep = False
        try:
            raw = bytearray()
            while not raw.endswith(b"\n"):
                chunk = peer.recv(min(65536, MAX_MESSAGE + 1 - len(raw)))
                if not chunk:
                    raise ValueError("Incomplete prompt gate request")
                raw.extend(chunk)
                if len(raw) > MAX_MESSAGE:
                    raise ValueError("Oversized prompt gate request")
            request = json.loads(raw)
            valid = (isinstance(request, dict)
                     and request.get("token") == self.token
                     and request.get("execution_id") == self.task["execution_id"]
                     and request.get("session_id") == self.task["id"]
                     and request.get("cwd") == self.task["cwd"])
            if not valid:
                peer.sendall(b'{"action":"block"}\n')
                return None
            prompt = request.get("prompt")
            if not isinstance(prompt, str):
                raise ValueError("invalid prompt")
            validate_prompt(prompt)
            if len(prompt.encode()) > 96 * 1024:
                peer.sendall(b'{"action":"block"}\n')
                return None
            # Claude submits the CLI's initial prompt through this hook too.
            # Consume the exemption once, never on a later identical message.
            initial, self.initial_hash = self.initial_hash, None
            if initial == hashlib.sha256(prompt.encode()).digest():
                peer.sendall(b'{"action":"continue"}\n')
                return None
            control = CONTROL.fullmatch(prompt.strip().lower())
            if prompt.strip().lower().startswith("ctr:") and not control:
                self.block(peer, "Escolha inválida; use o comando e o código exibidos, ou cancele o pedido.")
                return None
            if control:
                if not self.proposal or time.monotonic() > self.proposal[2]:
                    self.proposal = None
                    self.block(peer, "Confirmação expirada ou inválida. Reenvie seu pedido.")
                    return None
                if control[2] != self.proposal[1]:
                    self.block(peer, "Código inválido. " + self.proposal_reason(self.proposal[1]))
                    return None
                original, _, _ = self.proposal
                self.proposal = None
                if control[1] == "cancel":
                    self.block(peer, "Pedido cancelado; tarefa atual preservada.")
                    return None
                self.peer = peer
                keep = True
                return Handoff(original, "new" if control[1] == "new" else "continue")
            if self.proposal and time.monotonic() <= self.proposal[2]:
                self.block(peer, self.proposal_reason(self.proposal[1]))
                return None
            self.proposal = None
            action = detect(prompt, self.context)
            if action != "new":
                response = {"action": "continue"}
                if action == "ambiguous":
                    response["notice"] = ("[ctr] Fronteira incerta; tarefa e modelo preservados. "
                        "Para separar o pedido, use 'Nova tarefa: ...' ou 'New task: ...'.")
                peer.sendall(json.dumps(response).encode() + b"\n")
                return None
            if not boundary(prompt):
                code = secrets.token_hex(3)
                self.proposal = (prompt, code, time.monotonic() + 180)
                self.block(peer, self.proposal_reason(code))
                return None
            self.peer = peer
            keep = True
            return Handoff(prompt)
        except (OSError, ValueError, TypeError):
            try:
                peer.sendall(b'{"action":"block"}\n')
            except OSError:
                pass
            return None
        finally:
            if not keep:
                peer.close()

    @staticmethod
    def block(peer, reason):
        peer.sendall(json.dumps(dict(action="block", reason="[ctr] " + reason)).encode() + b"\n")

    @staticmethod
    def proposal_reason(code):
        return ("Parece um novo objetivo. O pedido ainda não foi executado. "
            "Substitua o rascunho (Ctrl-U) por uma escolha: "
            f"ctr:new {code} (nova tarefa), ctr:continue {code} (mesma tarefa), "
            f"ctr:cancel {code} (cancelar).")
