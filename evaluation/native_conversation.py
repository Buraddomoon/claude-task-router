#!/usr/bin/env python3
"""Opt-in native PTY exercise with metadata-only classification/signal evidence.

Pass router arguments after --. This runs the real Claude when the caller
launches it in a terminal; it is never invoked by offline CI. No prompts,
transcripts, credentials or command lines are copied into the record.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claude_task_router import classifier, cli
from claude_task_router.privacy import private_file


def main():
    raw = sys.argv[1:]
    if "--" not in raw:
        raise SystemExit("Use --record ARQUIVO [--interrupt-handoff] -- ARGUMENTOS_DO_CTR")
    index = raw.index("--")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--interrupt-handoff", action="store_true")
    args = parser.parse_args(raw[:index])
    router_args = raw[index + 1:]
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("Este roteiro exige terminal nativo; não substitua por modo print.")
    fd = private_file(args.record, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    def record(kind, **fields):
        row = dict(at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                   kind=kind, **fields)
        os.write(fd, (json.dumps(row) + "\n").encode())

    original_classify = classifier.classify
    original_signal = subprocess.Popen.send_signal
    interrupted = False
    calls = 0

    def classify(prompt, config=None):
        nonlocal calls
        started = time.perf_counter_ns()
        decision = original_classify(prompt, config)
        calls += 1
        record("classification", count=calls, model=decision.model, tier=decision.tier,
               duration_ns=time.perf_counter_ns() - started)
        return decision

    def send_signal(child, signum):
        nonlocal interrupted
        original_signal(child, signum)
        record("signal_sent", signal=int(signum))
        if args.interrupt_handoff and signum == signal.SIGTERM and not interrupted:
            interrupted = True
            record("injected_sigint")
            # An actual OS signal at the point after the old native client was
            # told to exit, before the supervisor can classify/start a successor.
            os.kill(os.getpid(), signal.SIGINT)

    files = ("cli.py", "launcher.py", "conversation.py", "conversation_hook.py", "topics.py", "state.py")
    record("start", source_sha256={name: hashlib.sha256((ROOT / "claude_task_router" / name).read_bytes()).hexdigest()
                                   for name in files}, interrupt_handoff=args.interrupt_handoff)
    try:
        with patch.object(classifier, "classify", classify), patch.object(cli, "classify", classify), \
             patch.object(subprocess.Popen, "send_signal", send_signal):
            code = cli.main(router_args)
        record("exit", code=code, classification_count=calls)
        return code
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
