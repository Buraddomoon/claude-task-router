from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from claude_task_router.cli import main
from claude_task_router.launcher import validate_extra
from claude_task_router.state import Store

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests/fake_claude.py"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="router space ' ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.state_dir = self.root / "state"
        self.log = self.root / "fake.jsonl"
        self.env = dict(os.environ, FAKE_LOG=str(self.log), PYTHONPATH=str(ROOT))
        for key in ("FAKE_MANUAL_MODEL", "FAKE_SLEEP", "FAKE_EXIT", "FAKE_READY", "FAKE_NO_MODEL", "FAKE_AUTO_MODEL"):
            self.env.pop(key, None)
        FAKE.chmod(0o755)

    def call(self, *args, env=None, cwd=None):
        return subprocess.run([sys.executable, "-m", "claude_task_router", "--state-dir",
                               str(self.state_dir), "--claude-bin", str(FAKE), *args],
                              cwd=cwd or self.project, env=env or self.env,
                              capture_output=True, text=True, timeout=15)

    def logs(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def task(self):
        return Store(self.state_dir).get("latest", self.project)

    def test_new_and_resume_preserve_session_and_resolved_model(self):
        first = self.call("new", "Fix typo", "--", "-p", "--output-format", "json")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["result"], "FAKE_RESPONSE")
        task = self.task()
        self.assertEqual(task["model"], "haiku")
        self.assertEqual(task["effective_model"], "claude-haiku-test-001")
        # Different continuation complexity must not trigger a new classification.
        second = self.call("resume", task["id"], "Design distributed architecture", "--", "-p")
        self.assertEqual(second.returncode, 0, second.stderr)
        logs = self.logs()
        self.assertEqual(logs[0]["session"], logs[1]["session"])
        self.assertEqual(logs[1]["model"], "claude-haiku-test-001")
        self.assertIn("--resume", logs[1]["argv"])
        self.assertEqual(self.task()["launches"], 2)

    def test_resume_does_not_read_config_or_call_classifier(self):
        result = self.call("new", "Fix typo", "--", "-p")
        self.assertEqual(result.returncode, 0, result.stderr)
        task = self.task()
        with patch("claude_task_router.cli.load_config", side_effect=AssertionError("config")), \
             patch("claude_task_router.cli.classify", side_effect=AssertionError("classification")), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--state-dir", str(self.state_dir), "--config", "missing.json",
                                   "resume", task["id"], "--dry-run"]), 0)

    def test_optional_hook_model_resolves_from_transcript(self):
        env = dict(self.env, FAKE_NO_MODEL="1", CLAUDE_CONFIG_DIR=str(self.root / "claude-config"))
        result = self.call("new", "Fix typo", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        task = self.task()
        self.assertEqual(task["model"], "haiku")
        self.assertEqual(task["effective_model"], "claude-haiku-test-001")
        self.assertIsNotNone(task["hook_seen_at"])
        result = self.call("resume", task["id"], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.logs()[-1]["model"], "claude-haiku-test-001")

    def test_manual_model_bypasses_classification(self):
        with patch("claude_task_router.cli.classify", side_effect=AssertionError("classification")), \
             redirect_stdout(io.StringIO()):
            code = main(["new", "any task", "--model", "opus", "--dry-run"])
            self.assertEqual(code, 0)

    def test_slash_model_change_persists(self):
        env = dict(self.env, FAKE_MANUAL_MODEL="claude-opus-manual")
        self.assertEqual(self.call("new", "Fix typo", env=env).returncode, 0)
        self.assertEqual(self.task()["model"], "claude-opus-manual")
        self.assertEqual(self.call("resume", self.task()["id"]).returncode, 0)
        self.assertEqual(self.logs()[-1]["model"], "claude-opus-manual")

    def test_auto_switch_preserves_choice_and_reports_divergence(self):
        result = self.call("new", "Fix typo", env=dict(self.env, FAKE_AUTO_MODEL="claude-sonnet-auto"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("divergência", result.stderr)
        task = self.task()
        self.assertEqual(task["model"], "haiku")
        self.assertEqual(task["effective_model"], "claude-sonnet-auto")
        self.assertEqual(task["resolved_model"], "claude-haiku-test-001")
        self.assertTrue(any(e["kind"] == "model_diverged" for e in Store(self.state_dir).events(task["id"])))
        self.assertEqual(self.call("resume", task["id"]).returncode, 0)
        self.assertEqual(self.logs()[-1]["model"], "claude-haiku-test-001")
        settings = json.loads(self.logs()[0]["argv"][self.logs()[0]["argv"].index("--settings") + 1])
        self.assertIs(settings["switchModelsOnFlag"], False)
        self.assertNotIn("availableModels", settings)

    def test_offline_and_resume_overrides(self):
        self.assertEqual(self.call("new", "Fix typo").returncode, 0)
        task_id = self.task()["id"]
        self.assertEqual(self.call("model", task_id, "sonnet").returncode, 0)
        self.assertEqual(self.call("resume", task_id).returncode, 0)
        self.assertEqual(self.logs()[-1]["model"], "sonnet")
        self.assertEqual(self.call("resume", task_id, "--model", "opus").returncode, 0)
        self.assertEqual(self.logs()[-1]["model"], "opus")

    def test_resume_from_other_directory_uses_original_cwd(self):
        self.assertEqual(self.call("new", "Fix typo").returncode, 0)
        other = self.root / "other"
        other.mkdir()
        result = self.call("resume", self.task()["id"], cwd=other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.logs()[-1]["cwd"], str(self.project.resolve()))

    def test_prompt_remains_literal_and_not_stored(self):
        marker = self.root / "PWNED"
        prompt = f'--model opus; touch {marker}; $(touch {marker}) `touch {marker}`'
        source = self.root / "prompt.txt"
        source.write_text(prompt)
        result = self.call("new", "--prompt-file", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.logs()[-1]["argv"]
        self.assertEqual(argv[-2:], ["--", prompt])
        self.assertFalse(marker.exists())
        self.assertNotIn(prompt.encode(), Store(self.state_dir).path.read_bytes())

    def test_dry_run_has_no_state_or_claude_process(self):
        result = self.call("new", "Fix typo", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["persisted"])
        self.assertFalse(self.state_dir.exists())
        self.assertFalse(self.log.exists())

    def test_exit_code_and_start_failure(self):
        result = self.call("new", "Fix typo", env=dict(self.env, FAKE_EXIT="7"))
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.task()["last_exit_code"], 7)
        fresh = self.root / "fresh"
        result = subprocess.run([sys.executable, "-m", "claude_task_router", "--state-dir",
                                 str(fresh), "--claude-bin", "nonexistent-binary-ctr",
                                 "new", "Fix typo"], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(fresh.exists())

    def test_dangerous_session_flags_rejected_before_creation(self):
        for args in (["--model", "opus"], ["--model=opus"], ["--resume", "x"],
                     ["--settings", "{}"], ["--fork-session"], ["--bare"], ["-pX"],
                     ["--worktree"], ["--no-session-persistence"], ["--fallback-model", "sonnet"]):
            with self.subTest(args=args):
                result = self.call("new", "Fix typo", "--", *args)
                self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.state_dir.exists())

    def test_value_flags_and_print_requirements(self):
        for args in (["--tools"], ["--output-format", "json"], ["--output-format="], ["--verbose=true"]):
            with self.assertRaises(ValueError):
                validate_extra(args)
        self.assertEqual(validate_extra(["-p", "--tools", "", "--output-format=json"]),
                         ["-p", "--tools", "", "--output-format=json"])

    def test_prompt_file_stdin(self):
        result = subprocess.run([sys.executable, "-m", "claude_task_router", "classify",
                                 "--prompt-file", "-", "--json"], input="Corrija o typo",
                                text=True, capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["tier"], "economy")

    def test_doctor_no_inference(self):
        result = self.call("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertFalse(self.log.exists())

    def test_running_task_rejects_concurrent_resume_and_model_edit(self):
        ready = self.root / "ready"
        command = [sys.executable, "-m", "claude_task_router", "--state-dir",
                   str(self.state_dir), "--claude-bin", str(FAKE), "new", "Fix typo"]
        process = subprocess.Popen(command, cwd=self.project,
            env=dict(self.env, FAKE_SLEEP="30", FAKE_READY=str(ready)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(process.communicate())
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            task_id = self.task()["id"]
            for args in (("resume", task_id), ("model", task_id, "opus")):
                result = self.call(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("já está em execução", result.stderr)
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143)
            self.assertEqual(self.task()["last_exit_code"], 143)
            # Parent retained the lock until the child exited, then released it.
            result = self.call("resume", task_id)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)

    def test_hook_ignores_invalid_payload_without_stdout(self):
        for raw in ("not-json", "[]", "{}", "x" * 65537):
            result = subprocess.run([sys.executable, str(ROOT / "claude_task_router/hook.py"),
                                     "--state-dir", str(self.state_dir)], input=raw,
                                    text=True, capture_output=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
