"""Run with the installed interpreter, from outside the source checkout."""

import json
import os
from pathlib import Path
import shutil
import sys
import subprocess

import claude_task_router

SOURCE = Path(__file__).resolve().parent.parent
assert not Path(claude_task_router.__file__).resolve().is_relative_to(SOURCE)
assert not Path.cwd().resolve().is_relative_to(SOURCE)
root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
project = root / "project with space '"
project.mkdir(exist_ok=True)
fake = root / "fake claude"
shutil.copy2(SOURCE / "tests/fake_claude.py", fake)
fake.chmod(0o755)
state = root / "state"
env = {key: value for key, value in os.environ.items() if not key.startswith("FAKE_")}
env.update(FAKE_LOG=str(root / "calls.jsonl"), FAKE_SESSION_DIR=str(root / "sessions"))
ctr = str(Path(sys.executable).parent / "ctr")


def call(*args, code=0):
    result = subprocess.run([ctr, "--state-dir", str(state), "--claude-bin", str(fake), *args],
                            cwd=project, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == code, (args, result.stdout, result.stderr)
    return result


snapshot = root / "before.json"
if not snapshot.exists():
    assert json.loads(call("doctor").stdout)["ok"]
    assert json.loads(call("classify", "Fix typo", "--json").stdout)["tier"] == "economy"
    assert json.loads(call("new", "Fix typo", "--", "-p").stdout)["result"] == "FAKE_RESPONSE"
    task = json.loads(call("show").stdout)
    call("model", task["id"], "opus")
    call("resume", task["id"], "Implement a distributed architecture", "--", "-p")
    task = json.loads(call("show", task["id"]).stdout)
    assert task["model"] == "opus" and task["effective_model"] == "claude-opus-test-001"
    assert task["launches"] == 2
    # Exercise real installed hooks for the slash-command contract as well.
    env["FAKE_MANUAL_MODEL"] = "claude-sonnet-manual"
    call("resume", task["id"], "--", "-p")
    env.pop("FAKE_MANUAL_MODEL")
    task = json.loads(call("show", task["id"]).stdout)
    assert task["model"] == "claude-sonnet-manual"
    snapshot.write_text(json.dumps(task))
else:
    before = json.loads(snapshot.read_text())
    # Bad config must never be read during a continuation.
    call("--config", str(root / "missing-config"), "resume", before["id"], "--", "-p")
    after = json.loads(call("show", before["id"]).stdout)
    for field in ("id", "cwd", "model", "resolved_model", "initial_model", "config", "decision",
                  "created_at", "prompt_sha256", "prompt_chars"):
        assert after[field] == before[field], field
    assert after["execution_id"] != before["execution_id"]
    assert after["observed_at"] and after["last_exit_code"] == 0
    assert after["events"][:len(before["events"])] == before["events"]
calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
assert len({entry["session"] for entry in calls}) == 1
assert all(entry["cwd"] == str(project.resolve()) for entry in calls)
assert b"Implement a distributed architecture" not in (state / "tasks.sqlite3").read_bytes()
print(json.dumps(dict(installed_from=str(Path(claude_task_router.__file__).resolve()),
                      task_id=calls[0]["session"], native_calls=len(calls), offline=True)))
