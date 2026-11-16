from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from claude_task_router.classifier import classify
from claude_task_router.config import Config
from claude_task_router.conversation import Handoff, PromptGate, boundary
from claude_task_router.launcher import run_conversation
from claude_task_router.state import Store

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests/fake_claude.py"


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ctr conversation '")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "state")
        self.log = self.root / "executed.jsonl"
        self.env = dict(os.environ, FAKE_LOG=str(self.root / "launches.jsonl"),
                        FAKE_EXECUTED_LOG=str(self.log), PYTHONPATH=str(ROOT))
        FAKE.chmod(0o755)

    def task(self, prompt="Fix typo in README", model=None):
        decision = classify(prompt).to_dict()
        if model:
            decision.update(model=model, tier="manual", policy="manual")
        return self.store.create(self.project, prompt, decision, Config().snapshot())

    def test_only_explicit_non_negated_unquoted_markers_replace_a_process(self):
        for text in ("Nova tarefa: implemente OAuth", "Novo assunto: implemente OAuth",
                     "New topic: implement OAuth", "Switching topics: fix a typo"):
            self.assertTrue(boundary(text), text)
        for text in ("Continue", "Now test it", "Nova tarefa não; continue isso",
                     'Traduza "nova tarefa: implemente OAuth"',
                     '"New task: build something"', "New task? Maybe later",
                     "Nova tarefa: não inicie nada", "New task: maybe later",
                     "New task: don't start anything", "New task: do not start anything",
                     "Nova tarefa: continue os testes e talvez faça outro serviço depois",
                     "New task: continue testing and perhaps build another service later",
                     "Nova tarefa: 'isto é apenas um exemplo'", "New task:"):
            self.assertFalse(boundary(text), text)

    def test_gate_identity_size_initial_exemption_once_and_memory_only(self):
        prompt = "New task: fix a typo"
        task = self.task(prompt)
        self.store.launched(task["id"])
        task = self.store.get(task["id"])
        with PromptGate(task, prompt) as gate:
            def request(**changes):
                payload = dict(token=gate.token, execution_id=task["execution_id"],
                    session_id=task["id"], cwd=task["cwd"], prompt=prompt)
                payload.update(changes)
                peer = socket.socket(socket.AF_UNIX)
                self.addCleanup(peer.close)
                peer.settimeout(3)
                peer.connect(gate.path)
                # Read concurrently with the sender, as the real helper does.
                # macOS socket buffers cannot hold the oversized case at once.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    sent = executor.submit(peer.sendall, json.dumps(payload).encode() + b"\n")
                    outcome = gate.poll()
                    sent.result(timeout=3)
                return outcome, None if outcome else json.loads(peer.recv(4096))

            for changes in ({"execution_id": "stale"}, {"session_id": "foreign"},
                            {"cwd": "/foreign"}, {"token": "wrong"}, {"prompt": None},
                            {"prompt": "x" * (96 * 1024 + 1)}):
                outcome, reply = request(**changes)
                self.assertIsNone(outcome)
                self.assertEqual(reply["action"], "block")
            self.assertEqual(request(prompt="ctr:new 123abc")[1]["action"], "block")
            self.assertEqual(request()[1]["action"], "continue")
            self.assertEqual(request()[0], Handoff(prompt))
            self.assertEqual(list(Path(gate.directory.name).iterdir()), [Path(gate.path)])
        self.assertFalse(Path(gate.path).exists())
        self.assertNotIn(prompt.encode(), self.store.path.read_bytes())

    def test_handoff_classifies_once_preserves_override_and_releases_old_lock(self):
        task = self.task(model="haiku")
        next_prompt = "Nova tarefa: escreva uma função para somar dois números"
        self.env["FAKE_CHAT_PLAN"] = json.dumps([
            [{"model": "opus"}, "Continue com os testes", next_prompt],
            ["Now check the result", 'Traduza "new task"',
             "Nova tarefa não; continue a correção"]])
        with patch.dict(os.environ, self.env, clear=True), \
             patch("claude_task_router.classifier.classify", wraps=classify) as classifier:
            code = run_conversation(self.store, task, str(FAKE), "Fix typo in README", [], False)
        self.assertEqual(code, 0)
        self.assertEqual(classifier.call_count, 1)
        self.assertEqual(classifier.call_args.args[0], next_prompt)
        tasks = self.store.list_tasks(self.project)
        self.assertEqual(len(tasks), 2)
        new = self.store.get(tasks[0]["id"])
        old = self.store.get(task["id"])
        self.assertEqual(old["model"], "opus")
        self.assertEqual(old["last_exit_code"], 0)
        self.assertEqual(new["model"], "sonnet")
        executed = [json.loads(line) for line in self.log.read_text().splitlines()]
        routed = [row for row in executed if row["prompt"] == next_prompt]
        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["session_id"], new["id"])
        continuation = next(row for row in executed if row["prompt"] == "Continue com os testes")
        self.assertEqual(continuation["model"], "opus")
        self.assertTrue(any(e["kind"] == "handoff_from" and e["source"] == old["id"]
                            for e in self.store.events(new["id"])))
        for current in (old, new):
            with self.store.task_lock(current["id"]):
                pass
            self.assertTrue(current["finished_at"])
        self.assertNotIn(next_prompt.encode(), self.store.path.read_bytes())

    def test_initial_boundary_replayed_once_and_new_client_error_is_not_retried(self):
        prompt = "New task: fix a typo in README"
        task = self.task(prompt, model="opus")
        self.env.update(FAKE_CHAT_PLAN=json.dumps([[prompt], []]), FAKE_EXIT="7")
        with patch.dict(os.environ, self.env, clear=True):
            code = run_conversation(self.store, task, str(FAKE), prompt, [], False)
        self.assertEqual(code, 7)
        launches = [json.loads(line) for line in (self.root / "launches.jsonl").read_text().splitlines()]
        self.assertEqual(len(launches), 2)
        self.assertEqual(launches[0]["model"], "opus")
        self.assertEqual(launches[1]["model"], "sonnet")
        executed = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(executed), 2)  # Initial task, then one intentional repeat as a new task.
        self.assertNotEqual(executed[0]["session_id"], executed[1]["session_id"])

    def test_gate_failure_blocks_without_context_or_prompt_echo(self):
        result = subprocess.run([sys.executable, str(ROOT / "claude_task_router/conversation_hook.py"),
            "--socket", str(self.root / "missing"), "--token", "test", "--execution-id", "test"],
            input=json.dumps(dict(hook_event_name="UserPromptSubmit", prompt="PRIVATE_SENTINEL")),
            capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertEqual(output["decision"], "block")
        self.assertNotIn("PRIVATE_SENTINEL", result.stdout + result.stderr)
        self.assertNotIn("additionalContext", result.stdout)
        self.assertTrue(output["hookSpecificOutput"]["suppressOriginalPrompt"])

    def test_forced_exit_does_not_start_a_successor(self):
        task = self.task()
        self.env.update(FAKE_CHAT_PLAN=json.dumps([["New task: implement OAuth"]]),
                        FAKE_IGNORE_TERM="1")
        with patch.dict(os.environ, self.env, clear=True), \
             patch("claude_task_router.classifier.classify", side_effect=AssertionError("classification")):
            code = run_conversation(self.store, task, str(FAKE), None, [], False)
        self.assertEqual(code, 137)
        self.assertEqual(len(self.store.list_tasks(self.project)), 1)
        self.assertEqual(self.store.get(task["id"])["last_exit_code"], 137)
        with self.store.task_lock(task["id"]):
            pass

    def test_creation_failure_preserves_previous_task_without_retry(self):
        task = self.task()
        self.env["FAKE_CHAT_PLAN"] = json.dumps([["New task: implement OAuth"]])
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(self.store, "create", side_effect=OSError("state unavailable")):
            with self.assertRaisesRegex(ValueError, "anterior .* preservada"):
                run_conversation(self.store, task, str(FAKE), None, [], False)
        self.assertEqual(len(self.store.list_tasks(self.project)), 1)
        self.assertEqual(self.store.get(task["id"])["last_exit_code"], 0)
        with self.store.task_lock(task["id"]):
            pass

    def test_print_is_rejected_before_task_creation(self):
        result = subprocess.run([sys.executable, "-m", "claude_task_router", "--state-dir",
            str(self.root / "unused"), "new", "Fix typo", "--conversation-routing", "--", "-p"],
            cwd=ROOT, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "unused").exists())

    def test_successor_and_links_rollback_together_if_previous_is_active(self):
        task = self.task()
        self.store.launched(task["id"])
        with self.assertRaisesRegex(ValueError, "parada"):
            self.store.create(self.project, "New task: fix typo", classify("fix typo").to_dict(),
                              Config().snapshot(), previous=task["id"])
        self.assertEqual(len(self.store.list_tasks(self.project)), 1)
        self.assertFalse(any(e["kind"] == "handoff_to" for e in self.store.events(task["id"])))

    def test_unavailable_gate_never_spawns_client_and_finishes_execution(self):
        task = self.task()
        with patch("claude_task_router.conversation.PromptGate", side_effect=OSError("no socket")), \
             patch("claude_task_router.launcher.subprocess.Popen", side_effect=AssertionError("spawn")):
            with self.assertRaisesRegex(OSError, "no socket"):
                run_conversation(self.store, task, str(FAKE), None, [], False)
        self.assertEqual(self.store.get(task["id"])["last_exit_code"], 2)

    def test_inferred_boundary_needs_live_choice_and_never_echoes_goal(self):
        task = self.task("Translate navigation labels")
        self.store.launched(task["id"])
        task = self.store.get(task["id"])
        goal = "Create a backup routine for local files"
        with PromptGate(task, "Translate navigation labels") as gate:
            def send(prompt):
                request = dict(token=gate.token, execution_id=task["execution_id"],
                    session_id=task["id"], cwd=task["cwd"], prompt=prompt)
                peer = socket.socket(socket.AF_UNIX)
                self.addCleanup(peer.close)
                peer.settimeout(2)
                peer.connect(gate.path)
                peer.sendall(json.dumps(request).encode() + b"\n")
                outcome = gate.poll()
                reply = None if outcome else json.loads(peer.recv(4096))
                return outcome, reply

            outcome, reply = send(goal)
            self.assertIsNone(outcome)
            self.assertEqual(reply["action"], "block")
            self.assertNotIn(goal, reply["reason"])
            nonce = gate.proposal[1]
            wrong = "ffffff" if nonce != "ffffff" else "000000"
            self.assertEqual(send("ctr:new " + wrong)[1]["action"], "block")
            # A stale/invalid control cannot reach Claude or replace the goal.
            self.assertEqual(gate.proposal[0], goal)
            self.assertEqual(send("ctr:cancel " + nonce)[1]["action"], "block")
            self.assertIsNone(gate.proposal)
            self.assertEqual(send("ctr:new " + nonce)[1]["action"], "block")
            send(goal)
            nonce = gate.proposal[1]
            gate.proposal = (goal, nonce, time.monotonic() - 1)
            self.assertEqual(send("ctr:new " + nonce)[1]["action"], "block")
            self.assertIsNone(gate.proposal)
            send(goal)
            nonce = gate.proposal[1]
            self.assertEqual(send("sim")[1]["action"], "block")
            self.assertEqual(send("ctr:typo " + nonce)[1]["action"], "block")
            self.assertEqual(gate.proposal[0], goal)
            outcome, _ = send("ctr:continue " + nonce)
            self.assertEqual(outcome, Handoff(goal, "continue"))
            self.assertIsNone(gate.proposal)
        self.assertEqual(len(self.store.list_tasks(self.project)), 1)
        self.assertNotIn(goal.encode(), self.store.path.read_bytes())

    def test_contextual_handoff_runs_goal_once_only_after_new_choice(self):
        initial = "Translate navigation labels"
        task = self.task(initial, model="haiku")
        goal = "Create a backup routine for local files"
        self.env["FAKE_CHAT_PLAN"] = json.dumps([[goal, {"choose": "new"}], ["Continue with tests"]])
        with patch.dict(os.environ, self.env, clear=True), \
             patch("claude_task_router.classifier.classify", wraps=classify) as classifier:
            code = run_conversation(self.store, task, str(FAKE), initial, [], False)
        self.assertEqual(code, 0)
        self.assertEqual(classifier.call_count, 1)
        executions = [json.loads(x) for x in self.log.read_text().splitlines()]
        goals = [x for x in executions if x["prompt"] == goal]
        self.assertEqual(len(goals), 1)
        self.assertNotEqual(goals[0]["session_id"], task["id"])
        self.assertFalse(any(x["prompt"].startswith("ctr:") for x in executions))

    def test_same_task_choice_preserves_uuid_manual_model_and_skips_classifier(self):
        initial = "Translate navigation labels"
        task = self.task(initial, model="haiku")
        goal = "Create a backup routine for local files"
        self.env["FAKE_CHAT_PLAN"] = json.dumps([
            [{"model": "opus"}, goal, {"choose": "continue"}], ["Continue with tests"]])
        with patch.dict(os.environ, self.env, clear=True), \
             patch("claude_task_router.classifier.classify", side_effect=AssertionError("classification")):
            code = run_conversation(self.store, task, str(FAKE), initial, [], False)
        self.assertEqual(code, 0)
        current = self.store.get(task["id"])
        self.assertEqual(current["model"], "opus")
        self.assertEqual(current["launches"], 2)
        self.assertEqual(len(self.store.list_tasks(self.project)), 1)
        executions = [json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertEqual({x["session_id"] for x in executions}, {task["id"]})
        self.assertEqual(sum(x["prompt"] == goal for x in executions), 1)
        self.assertEqual(next(x["model"] for x in executions if x["prompt"] == goal), "claude-opus-test-001")
