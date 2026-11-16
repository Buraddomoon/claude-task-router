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

from .classifier import normalize, validate_prompt
from .boundary import CONTINUE

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


def detect(prompt):
    if boundary(prompt):
        return "new"
    return "continue" if CONTINUE.match(normalize(prompt.strip())) else "ambiguous"


@dataclass
class Handoff:
    prompt: str


class PromptGate:
    def __init__(self, task, initial_prompt):
        self.task = task
        self.initial_hash = (hashlib.sha256(initial_prompt.encode()).digest()
                             if initial_prompt is not None else None)
        self.token = secrets.token_hex(32)
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
            action = detect(prompt)
            if action != "new":
                response = {"action": "continue"}
                if action == "ambiguous":
                    response["notice"] = ("[ctr] Fronteira incerta; tarefa e modelo preservados. "
                        "Para separar o pedido, use 'Nova tarefa: ...' ou 'New task: ...'.")
                peer.sendall(json.dumps(response).encode() + b"\n")
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
