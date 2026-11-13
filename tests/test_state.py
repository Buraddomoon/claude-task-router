import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from claude_task_router.classifier import classify
from claude_task_router.config import Config
from claude_task_router.state import Store


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        self.store = Store(self.cwd / "state")
        self.prompt = "Fix typo SECRET-TEST-PROMPT"
        self.task = self.store.create(self.cwd, self.prompt, classify(self.prompt).to_dict(),
                                      Config().snapshot())
        self.execution_id = self.store.launched(self.task["id"])

    def observe(self, payload):
        return self.store.observe(payload, self.execution_id)

    def test_metadata_only_and_permissions(self):
        task = self.store.get(self.task["id"][:8])
        self.assertEqual(task["prompt_chars"], len(self.prompt))
        self.assertNotIn(self.prompt, self.store.path.read_bytes().decode(errors="ignore"))
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(task["config"], Config().snapshot())

    def test_existing_private_permissions_are_repaired_and_links_are_refused(self):
        self.store.root.chmod(0o755)
        self.store.path.chmod(0o644)
        Store(self.store.root)
        self.assertEqual(self.store.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        target = self.cwd / "foreign"
        target.write_text("FOREIGN-CONTENT")
        target.chmod(0o644)
        for kind in ("symlink", "hardlink", "fifo"):
            root = self.cwd / kind
            root.mkdir(mode=0o700)
            db = root / "tasks.sqlite3"
            if kind == "symlink":
                db.symlink_to(target)
            elif kind == "hardlink":
                os.link(target, db)
            else:
                os.mkfifo(db)
            with self.subTest(kind=kind), self.assertRaises((OSError, ValueError)):
                Store(root)
            self.assertEqual(target.read_text(), "FOREIGN-CONTENT")
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        alias = self.cwd / "state-alias"
        alias.symlink_to(self.store.root)
        with self.assertRaises(OSError):
            Store(alias)

    def test_lock_symlink_does_not_touch_an_unrelated_file(self):
        directory = self.store.root / "locks"
        directory.mkdir()
        target = self.cwd / "unrelated"
        target.write_text("unchanged")
        (directory / (self.task["id"] + ".lock")).symlink_to(target)
        with self.assertRaises(OSError):
            with self.store.task_lock(self.task["id"]):
                self.fail("symlink lock followed")
        self.assertEqual(target.read_text(), "unchanged")

    def test_model_and_observation(self):
        self.store.set_model(self.task["id"], "sonnet")
        payload = dict(session_id=self.task["id"], cwd=str(self.cwd),
                       hook_event_name="PostModelSwitch", to_model="claude-opus-test", source="command")
        self.assertTrue(self.observe(payload))
        task = self.store.get(self.task["id"])
        self.assertEqual(task["model"], "claude-opus-test")
        self.assertEqual(task["initial_model"], "haiku")
        self.assertIsNotNone(task["observed_at"])
        self.assertEqual(len(self.store.events(task["id"])), 3)

    def test_only_manual_sources_change_intent(self):
        for source in ("command", "picker", "sdk"):
            with self.subTest(source=source):
                self.assertTrue(self.observe(dict(session_id=self.task["id"], cwd=str(self.cwd),
                    hook_event_name="PostModelSwitch", source=source, requested_model="opus",
                    to_model="claude-opus-test")))
                task = self.store.get(self.task["id"])
                self.assertEqual(task["model"], "opus")
                self.assertEqual(task["resolved_model"], "claude-opus-test")
        for source in ("auto", "resume"):
            self.observe(dict(session_id=self.task["id"], cwd=str(self.cwd),
                hook_event_name="PostModelSwitch", source=source, to_model="claude-sonnet-test"))
            self.assertEqual(self.store.get(self.task["id"])["model"], "opus")
        self.assertEqual(self.store.get(self.task["id"])["effective_model"], "claude-sonnet-test")

    def test_initial_substitution_never_becomes_choice(self):
        self.observe(dict(session_id=self.task["id"], cwd=str(self.cwd),
            hook_event_name="SessionStart", source="startup", model="claude-opus-fallback"))
        task = self.store.get(self.task["id"])
        self.assertEqual(task["model"], "haiku")
        self.assertIsNone(task["resolved_model"])
        self.assertEqual(task["effective_model"], "claude-opus-fallback")
        self.assertEqual(self.store.events(task["id"])[-2]["kind"], "model_diverged")

    def test_unknown_session_and_wrong_cwd_ignored(self):
        payload = dict(session_id=self.task["id"], cwd="/elsewhere", source="startup",
                       hook_event_name="SessionStart", model="claude-haiku-test")
        self.assertFalse(self.observe(payload))
        payload.update(cwd=str(self.cwd), session_id="not-a-managed-session")
        self.assertFalse(self.observe(payload))
        self.assertEqual(self.store.get(self.task["id"])["model"], "haiku")

    def test_locks_reject_duplicate_but_allow_other_tasks(self):
        other = self.store.create(self.cwd, "hello", classify("hello").to_dict(), {})
        with self.store.task_lock(self.task["id"]):
            with self.assertRaisesRegex(ValueError, "já está"):
                with self.store.task_lock(self.task["id"]):
                    self.fail("duplicate lock acquired")
            with self.store.task_lock(other["id"]):
                pass
        with self.store.task_lock(self.task["id"]):
            pass

    def test_latest_is_project_scoped_and_tracks_launch(self):
        other = self.store.create(self.cwd, "hello", classify("hello").to_dict(), {})
        self.assertEqual(self.store.get("latest", self.cwd)["id"], other["id"])
        self.store.launched(self.task["id"])
        self.assertEqual(self.store.get("latest", self.cwd)["id"], self.task["id"])
        self.store.finished(self.task["id"], 7)
        self.assertEqual(self.store.get(self.task["id"])["last_exit_code"], 7)
        with self.assertRaises(ValueError):
            self.store.get("latest", self.cwd / "another")

    def test_bad_references(self):
        for ref in ("../../escape", "x", "%", "' OR 1=1"):
            with self.assertRaises(ValueError):
                self.store.get(ref)

    def test_transcript_ignores_old_wrong_session_and_newer_manual_switch(self):
        config_root = self.cwd / "claude-config"
        transcript = config_root / "projects/fake" / (self.task["id"] + ".jsonl")
        transcript.parent.mkdir(parents=True)
        with patch.dict("os.environ", CLAUDE_CONFIG_DIR=str(config_root)):
            self.observe(dict(session_id=self.task["id"], cwd=str(self.cwd), source="startup",
                hook_event_name="SessionStart", transcript_path=str(transcript)))
            old = datetime.now(timezone.utc) - timedelta(hours=1)
            def entry(session, at, model):
                return json.dumps(dict(type="assistant", sessionId=session,
                                       timestamp=at.isoformat(), message=dict(model=model)))
            transcript.write_text(entry(self.task["id"], old, "old-model") + "\n" +
                                  entry("wrong-session", datetime.now(timezone.utc), "wrong-model") + "\n")
            self.assertFalse(self.store.reconcile_transcript(self.task["id"]))
            with transcript.open("a") as stream:
                stream.write(entry(self.task["id"], datetime.now(timezone.utc), "real-model") + "\n")
            self.observe(dict(session_id=self.task["id"], cwd=str(self.cwd), source="command",
                hook_event_name="PostModelSwitch", to_model="manual-newer"))
            self.assertFalse(self.store.reconcile_transcript(self.task["id"]))
            self.assertEqual(self.store.get(self.task["id"])["model"], "manual-newer")

    def test_execution_reset_and_late_hooks(self):
        payload = dict(session_id=self.task["id"], cwd=str(self.cwd), source="startup",
                       hook_event_name="SessionStart", model="claude-haiku-test")
        self.assertTrue(self.observe(payload))
        previous = self.execution_id
        current = self.store.launched(self.task["id"])
        task = self.store.get(self.task["id"])
        self.assertNotEqual(previous, current)
        self.assertIsNone(task["observed_at"])
        self.assertIsNone(task["effective_model"])
        self.assertEqual(task["resolved_model"], "claude-haiku-test")
        self.assertFalse(self.store.observe(payload, previous))
        self.assertFalse(self.store.observe(payload))
        self.store.finished(self.task["id"], 0)
        self.store.set_model(self.task["id"], "opus")
        payload.update(hook_event_name="PostModelSwitch", to_model="sonnet", source="command")
        self.assertFalse(self.store.observe(payload, current))
        self.assertEqual(self.store.get(self.task["id"])["model"], "opus")

    def test_partial_and_delayed_startup_payload(self):
        payload = dict(session_id=self.task["id"], cwd=str(self.cwd), source="startup",
                       hook_event_name="SessionStart")
        self.assertTrue(self.observe(payload))
        self.assertIsNone(self.store.get(self.task["id"])["observed_at"])
        self.assertFalse(self.store.reconcile_transcript(self.task["id"]))
        self.assertTrue(self.observe(dict(payload, source="picker", hook_event_name="PostModelSwitch",
                                          to_model="opus")))
        self.assertFalse(self.observe(dict(payload, model="haiku")))
        self.assertEqual(self.store.get(self.task["id"])["effective_model"], "opus")

    def test_transcript_cannot_confirm_prior_run_or_pre_manual_choice(self):
        config = self.cwd / "claude-config"
        path = config / "projects/fake" / (self.task["id"] + ".jsonl")
        path.parent.mkdir(parents=True)
        at = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(dict(type="assistant", sessionId=self.task["id"],
            timestamp=at, message=dict(model="claude-haiku-old"))) + "\n")
        self.execution_id = self.store.launched(self.task["id"])
        with patch.dict("os.environ", CLAUDE_CONFIG_DIR=str(config)):
            self.assertTrue(self.observe(dict(session_id=self.task["id"], cwd=str(self.cwd),
                source="resume", hook_event_name="SessionStart", transcript_path=str(path))))
            self.assertFalse(self.store.reconcile_transcript(self.task["id"]))
            self.store.set_model(self.task["id"], "opus")
            self.assertFalse(self.store.reconcile_transcript(self.task["id"]))
            self.assertIsNone(self.store.get(self.task["id"])["observed_at"])

    def test_reconciliation_compare_and_set_rejects_concurrent_changes(self):
        config = self.cwd / "claude-config"
        path = config / "projects/fake" / (self.task["id"] + ".jsonl")
        path.parent.mkdir(parents=True)
        original_open = Path.open
        for change in ("execution", "manual_aba", "partial_hook"):
            with self.subTest(change=change), patch.dict("os.environ", CLAUDE_CONFIG_DIR=str(config)):
                self.store.set_model(self.task["id"], "haiku")
                self.execution_id = self.store.launched(self.task["id"])
                payload = dict(session_id=self.task["id"], cwd=str(self.cwd), source="startup",
                    hook_event_name="SessionStart", transcript_path=str(path))
                self.assertTrue(self.observe(payload))
                path.write_text(json.dumps(dict(type="assistant", sessionId=self.task["id"],
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=dict(model="claude-haiku-test"))) + "\n")
                intercepted = []
                def concurrent_open(target, *args, **kwargs):
                    if target.resolve() == path.resolve():
                        intercepted.append(change)
                        if change == "execution":
                            self.store.launched(self.task["id"])
                        elif change == "manual_aba":
                            self.store.set_model(self.task["id"], "opus")
                            self.store.set_model(self.task["id"], "haiku")
                        else:
                            self.assertTrue(self.observe(dict(payload, source="auto",
                                hook_event_name="PostModelSwitch")))
                    return original_open(target, *args, **kwargs)
                with patch.object(Path, "open", new=concurrent_open):
                    self.assertFalse(self.store.reconcile_transcript(self.task["id"]))
                self.assertEqual(intercepted, [change])
                task = self.store.get(self.task["id"])
                self.assertIsNone(task["observed_at"])
                self.assertEqual(task["model"], "haiku")

    def test_transcript_path_is_restricted(self):
        self.assertIsNone(self.store.valid_transcript("/etc/passwd", self.task["id"]))
        self.assertIsNone(self.store.valid_transcript(str(self.cwd / (self.task["id"] + ".jsonl")),
                                                      self.task["id"]))

    def test_schema_v1_migration_preserves_tasks(self):
        with self.store.connect() as db:
            db.execute("ALTER TABLE tasks DROP COLUMN transcript_path")
            db.execute("ALTER TABLE tasks DROP COLUMN hook_seen_at")
            db.execute("ALTER TABLE tasks DROP COLUMN effective_model")
            db.execute("ALTER TABLE tasks DROP COLUMN resolved_model")
            for column in ("execution_id", "finished_at", "choice_revision", "choice_changed_at"):
                db.execute(f"ALTER TABLE tasks DROP COLUMN {column}")
            db.execute("ALTER TABLE events DROP COLUMN execution_id")
            db.execute("PRAGMA user_version=1")
        migrated = Store(self.store.root)
        self.assertEqual(migrated.get(self.task["id"])["model"], "haiku")
        self.assertIsNone(migrated.get(self.task["id"])["transcript_path"])
