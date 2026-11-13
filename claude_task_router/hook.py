"""Silent hook entrypoint; executable by absolute path from any project."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

# Also works from a source checkout, without importing code from the user's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_task_router.state import Store  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--execution-id")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return 0
        payload = json.loads(raw)
        if isinstance(payload, dict):
            Store(args.state_dir).observe(payload, args.execution_id)
    except (ValueError, TypeError, OSError, sqlite3.Error):
        # Hooks must never inject error text into the model's context or block work.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
