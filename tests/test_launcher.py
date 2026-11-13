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
        for key in ("FAKE_MANUAL_MODEL", "FAKE_SLEEP", "FAKE_EXIT", "FAKE_READY", "FAKE_NO_MODEL", "FAKE_AUTO_MODEL", "FAKE_NO_HOOKS",
                    "FAKE_ABORT_BEFORE_SESSION", "FAKE_SESSION_DIR", "FAKE_SIGINT_CONTINUE"):
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

    def test_resume_without_hooks_needs_current_confirmation(self):
        self.assertEqual(self.call("new", "Fix typo").returncode, 0)
        before = self.task()
        self.assertIsNotNone(before["observed_at"])
        result = self.call("resume", before["id"], env=dict(self.env, FAKE_NO_HOOKS="1"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("modelo efetivo não observado", result.stderr)
        task = self.task()
        self.assertNotEqual(task["execution_id"], before["execution_id"])
        self.assertIsNone(task["observed_at"])
        self.assertIsNone(task["hook_seen_at"])
        self.assertIsNone(task["effective_model"])
        self.assertEqual(task["resolved_model"], before["resolved_model"])

    def test_manual_model_bypasses_classification(self):
        with patch("claude_task_router.cli.classify", side_effect=AssertionError("classification")), \
             redirect_stdout(io.StringIO()):
            code = main(["new", "any task", "--model", "opus", "--dry-run"])
            self.assertEqual(code, 0)

    def test_auto_entry_reuses_only_clear_project_continuations(self):
        self.assertEqual(self.call("run", "Fix typo").returncode, 0)
        task = self.task()
        with patch("claude_task_router.cli.classify", side_effect=AssertionError("classification")), \
             patch("claude_task_router.cli.load_config", side_effect=AssertionError("config")), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["--state-dir", str(self.state_dir), "--claude-bin", str(FAKE),
                         "--config", "missing.json", "run", "Continue e implemente autenticação",
                         "--cwd", str(self.project)])
        self.assertEqual(code, 0)
        self.assertEqual(self.task()["id"], task["id"])
        self.assertEqual(self.task()["model"], "haiku")
        self.assertEqual(self.call("run", "Implement OAuth").returncode, 0)
        self.assertNotEqual(self.task()["id"], task["id"])
        self.assertEqual(self.task()["model"], "opus")

    def test_bare_entry_shorthand_overrides_and_dry_run(self):
        planned = self.call("run", "Fix typo", "--dry-run")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertFalse(self.state_dir.exists())
        self.assertEqual(self.call("Fix typo").returncode, 0)
        before = self.task()
        self.assertEqual(self.call().returncode, 0)
        self.assertEqual(self.task()["id"], before["id"])
        self.assertEqual(self.call("run", "Continue", "--new").returncode, 0)
        self.assertNotEqual(self.task()["id"], before["id"])
        self.assertEqual(self.call("run", "--continue", "--dry-run").returncode, 0)

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

    def test_aborted_first_launch_and_missing_session_recover_explicitly(self):
        sessions = self.root / "native-sessions"
        env = dict(self.env, FAKE_SESSION_DIR=str(sessions))
        first = self.call("new", "Fix typo", "--model", "opus",
                          env=dict(env, FAKE_ABORT_BEFORE_SESSION="1"))
        self.assertEqual(first.returncode, 130, first.stderr)
        original = self.task()
        self.assertEqual(original["last_exit_code"], 130)
        self.assertIsNotNone(original["finished_at"])
        self.assertIn("ctr recover", first.stderr)
        failed = self.call("resume", original["id"], env=env)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("No conversation found", failed.stderr)
        self.assertIn("ctr recover", failed.stderr)
        self.assertEqual(len(self.logs()), 2)  # No hidden retry.
        recovered = self.call("--config", "missing.json", "recover", original["id"],
                              "Fresh context SECRET-RECOVERY-PROMPT", env=env)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        replacement = self.task()
        self.assertNotEqual(replacement["id"], original["id"])
        self.assertEqual(replacement["model"], "opus")
        self.assertEqual(replacement["config"], original["config"])
        self.assertEqual(replacement["decision"], original["decision"])
        event = Store(self.state_dir).events(replacement["id"])[0]
        self.assertEqual((event["kind"], event["source"]), ("recovered_from", original["id"]))
        self.assertEqual(Store(self.state_dir).get(original["id"])["last_exit_code"], 1)
        self.assertNotIn(b"SECRET-RECOVERY-PROMPT", Store(self.state_dir).path.read_bytes())
        self.assertIn("--session-id", self.logs()[-1]["argv"])
        self.assertEqual(self.call("resume", replacement["id"], env=env).returncode, 0)

    def test_deleted_native_session_and_removed_project_have_actionable_recovery(self):
        sessions = self.root / "native-sessions"
        env = dict(self.env, FAKE_SESSION_DIR=str(sessions))
        self.assertEqual(self.call("new", "Fix typo", env=env).returncode, 0)
        original = self.task()
        (sessions / original["id"]).unlink()
        result = self.call("resume", original["id"], env=env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ctr recover", result.stderr)
        self.project.rmdir()
        before = len(self.logs())
        result = self.call("resume", original["id"], cwd=self.root, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--cwd", result.stderr)
        self.assertEqual(len(self.logs()), before)
        other = self.root / "replacement-project"
        other.mkdir()
        recovered = self.call("recover", original["id"], "Resume this work", "--cwd", str(other),
                              cwd=self.root, env=env)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        task = Store(self.state_dir).get("latest", other)
        self.assertEqual(task["model"], original["model"])
        self.assertEqual(task["resolved_model"], original["resolved_model"])
        self.assertEqual(self.logs()[-1]["model"], original["resolved_model"])
        self.assertEqual(Store(self.state_dir).get(original["id"])["cwd"], original["cwd"])

    def test_recovery_dry_run_and_missing_context_do_not_create_tasks(self):
        self.assertEqual(self.call("new", "Fix typo").returncode, 0)
        task = self.task()
        before = Store(self.state_dir).events(task["id"])
        result = self.call("recover", task["id"], "fresh context", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["reclassified"])
        self.assertEqual(self.task()["id"], task["id"])
        self.assertEqual(len(self.logs()), 1)
        self.assertEqual(Store(self.state_dir).events(task["id"]), before)
        result = self.call("recover", task["id"])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(self.logs()), 1)

    def test_recovery_never_loads_config_or_classifies(self):
        self.assertEqual(self.call("new", "Fix typo").returncode, 0)
        with patch("claude_task_router.cli.load_config", side_effect=AssertionError("config")), \
             patch("claude_task_router.cli.classify", side_effect=AssertionError("classifier")), \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--state-dir", str(self.state_dir), "--claude-bin", str(FAKE),
                                   "recover", self.task()["id"], "Fresh context"]), 0)

    def test_spawn_failure_records_completion_and_preserves_task(self):
        with patch("claude_task_router.launcher.subprocess.Popen", side_effect=OSError("cannot start")), \
             redirect_stderr(io.StringIO()) as err:
            code = main(["--state-dir", str(self.state_dir), "--claude-bin", str(FAKE),
                         "new", "Fix typo", "--cwd", str(self.project)])
        self.assertEqual(code, 2)
        self.assertIn("ctr recover", err.getvalue())
        task = self.task()
        self.assertEqual(task["last_exit_code"], 2)
        self.assertIsNotNone(task["finished_at"])
        self.assertEqual(task["model"], "haiku")
        self.assertEqual(self.call("resume", task["id"]).returncode, 0)

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

    def test_model_commands_reject_native_success_with_invalid_model_without_inference(self):
        for args, expected in ((("models",), 0), (("models", "--check", "haiku"), 0),
                               (("models", "--check", "invalid-router-model"), 1)):
            result = self.call(*args)
            self.assertEqual(result.returncode, expected, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["native_turns"], 0)
            self.assertEqual(payload["cli_estimated_cost_usd"], 0)
        self.assertFalse(self.state_dir.exists())
        self.assertFalse(self.log.exists())

    def test_doctor_exposes_only_authentication_status(self):
        result = self.call("doctor", env=dict(self.env, FAKE_LOGGED_OUT="1"))
        self.assertEqual(result.returncode, 1, result.stderr)
        auth = json.loads(result.stdout)["authentication"]
        self.assertEqual(auth, dict(logged_in=False, method="simulated", provider=None))
        self.assertFalse(self.log.exists())

    def test_print_timeout_preserves_metadata_and_releases_lock(self):
        result = self.call("new", "Fix typo", "--timeout", "0.3", "--", "-p",
                           env=dict(self.env, FAKE_SLEEP="30"))
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("Tempo limite", result.stderr)
        task = self.task()
        self.assertEqual(task["last_exit_code"], 124)
        self.assertIsNotNone(task["finished_at"])
        self.assertEqual(self.call("resume", task["id"]).returncode, 0)

    def test_invalid_timeouts_fail_before_state_or_process(self):
        for args in (("--timeout", "1"), ("--timeout", "nan", "--", "-p"),
                     ("--timeout", "-1", "--", "-p")):
            result = self.call("new", "Fix typo", *args)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.state_dir.exists())
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
            for args in (("resume", task_id), ("model", task_id, "opus"),
                         ("recover", task_id, "fresh context")):
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

    def test_sigint_keeps_lock_until_child_exits_then_allows_resume(self):
        ready = self.root / "sigint-ready"
        process = subprocess.Popen(
            [sys.executable, "-m", "claude_task_router", "--state-dir", str(self.state_dir),
             "--claude-bin", str(FAKE), "new", "Fix typo"],
            cwd=self.project, start_new_session=True,
            env=dict(self.env, FAKE_SLEEP="30", FAKE_READY=str(ready), FAKE_SIGINT_CONTINUE="1"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(process.communicate())
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            task = self.task()
            # Terminal SIGINT reaches the whole foreground group. The native
            # client may cancel input and remain alive after the first signal.
            os.killpg(process.pid, signal.SIGINT)
            result = self.call("resume", task["id"])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("já está em execução", result.stderr)
            os.killpg(process.pid, signal.SIGINT)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 130)
            self.assertEqual(self.task()["last_exit_code"], 130)
            self.assertEqual(self.call("resume", task["id"]).returncode, 0)
            self.assertEqual(self.logs()[-1]["session"], task["id"])
            self.assertEqual(self.logs()[-1]["model"], task["resolved_model"])
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
