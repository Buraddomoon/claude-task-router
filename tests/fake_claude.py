#!/usr/bin/env python3
"""Deterministic CLI contract double. Never makes an API call."""

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import signal
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.323 (Claude Code simulated)")
    sys.exit(0)
if args == ["--help"]:
    print("--model --resume --session-id --settings")
    sys.exit(0)


def value(flag):
    return args[args.index(flag) + 1]


session = value("--resume" if "--resume" in args else "--session-id")
model = value("--model")
if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a") as stream:
        stream.write(json.dumps(dict(argv=args, cwd=str(Path.cwd()), session=session,
                                     model=model)) + "\n")
# Optional native-session persistence for recovery tests.
if os.environ.get("FAKE_ABORT_BEFORE_SESSION"):
    sys.exit(130)
if os.environ.get("FAKE_SESSION_DIR"):
    sessions = Path(os.environ["FAKE_SESSION_DIR"])
    sessions.mkdir(parents=True, exist_ok=True)
    session_file = sessions / session
    if "--resume" in args and not session_file.exists():
        print("No conversation found with session ID: " + session, file=sys.stderr)
        sys.exit(1)
    session_file.touch()
settings = json.loads(value("--settings"))
source = "resume" if "--resume" in args else "startup"
active = {"haiku": "claude-haiku-test-001", "sonnet": "claude-sonnet-test-001",
          "opus": "claude-opus-test-001"}.get(model, model)
payload = dict(session_id=session, cwd=str(Path.cwd()), hook_event_name="SessionStart",
               model=active, source=source)
transcript = None
if os.environ.get("FAKE_NO_MODEL"):
    payload.pop("model")
    transcript = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects/fake" / (session + ".jsonl")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    payload["transcript_path"] = str(transcript)


def hook(event, payload):
    for entry in settings["hooks"][event]:
        for handler in entry["hooks"]:
            result = subprocess.run(handler["command"], shell=True, input=json.dumps(payload),
                                    text=True, capture_output=True)
            if result.returncode or result.stdout or result.stderr:
                print("Hook was not silent", file=sys.stderr)
                sys.exit(90)


if not os.environ.get("FAKE_NO_HOOKS"):
    hook("SessionStart", payload)
if os.environ.get("FAKE_MANUAL_MODEL"):
    hook("PostModelSwitch", dict(payload, hook_event_name="PostModelSwitch",
                                 to_model=os.environ["FAKE_MANUAL_MODEL"], source="command"))
if os.environ.get("FAKE_AUTO_MODEL"):
    hook("PostModelSwitch", dict(payload, hook_event_name="PostModelSwitch",
                                 to_model=os.environ["FAKE_AUTO_MODEL"], source="auto"))
if os.environ.get("FAKE_SIGINT_CONTINUE"):
    interrupts = 0

    def interrupt(_signum, _frame):
        global interrupts
        interrupts += 1
        if interrupts > 1:
            sys.exit(130)

    signal.signal(signal.SIGINT, interrupt)
if os.environ.get("FAKE_READY"):
    Path(os.environ["FAKE_READY"]).touch()
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if transcript:
    with transcript.open("a") as stream:
        stream.write(json.dumps(dict(type="assistant", sessionId=session,
            timestamp=datetime.now(timezone.utc).isoformat(), message=dict(model=active))) + "\n")
print(json.dumps(dict(session_id=session, result="FAKE_RESPONSE")))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
