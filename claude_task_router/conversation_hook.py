"""Fail closed prompt transport; stdout only contains native block decisions."""

import argparse
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_task_router.conversation import MAX_MESSAGE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--execution-id", required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_MESSAGE + 1)
        if len(raw) > MAX_MESSAGE:
            raise ValueError("oversized input")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
            raise ValueError("wrong event")
        request = {key: payload.get(key) for key in ("session_id", "cwd", "prompt")}
        request.update(token=args.token, execution_id=args.execution_id)
        encoded = json.dumps(request).encode() + b"\n"
        if len(encoded) > MAX_MESSAGE:
            raise ValueError("oversized request")
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(8)
            peer.connect(args.socket)
            peer.sendall(encoded)
            response = bytearray()
            while not response.endswith(b"\n"):
                chunk = peer.recv(1024)
                if not chunk or len(response) + len(chunk) > 4096:
                    raise ValueError("invalid response")
                response.extend(chunk)
            output = json.loads(response)
            if output.get("action") == "continue":
                if output.get("notice"):
                    print(json.dumps({"systemMessage": output["notice"]}))
                return 0
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    print(json.dumps({"decision": "block", "reason":
        "[ctr] Controle da tarefa indisponível ou sessão alterada. Pedido não executado. "
        "Retome a tarefa pelo ctr e reenvie o pedido.", "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": True}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
