"""Old databases and competing processes exercise real SQLite transactions."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from claude_task_router.classifier import classify
from claude_task_router.config import Config
from claude_task_router.state import Store

ROOT = Path(__file__).resolve().parent.parent
WORKER = """
from pathlib import Path
import sys
from claude_task_router.state import Store
from claude_task_router.classifier import classify
root, ready = map(Path, sys.argv[1:])
ready.touch()
store = Store(root)
store.create(root, 'Fix typo', classify('Fix typo').to_dict(), {})
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def legacy_store(self, version):
        store = Store(self.root / f"v{version}")
        task = store.create(self.root, "Fix typo PRIVATE-MIGRATION-PROMPT",
                            classify("Fix typo").to_dict(), Config().snapshot())
        with store.connect() as db:
            # Reproduce the legacy bug: a manual choice followed by auto fallback.
            db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                       (task["id"], task["created_at"], "PostModelSwitch", "sonnet", "picker"))
            db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                       (task["id"], task["created_at"], "PostModelSwitch", "opus", "auto"))
            db.execute("UPDATE tasks SET model='opus',observed_at=? WHERE id=?",
                       (task["created_at"], task["id"]))
            if version < 4:
                for column in ("execution_id", "finished_at", "choice_revision", "choice_changed_at"):
                    db.execute(f"ALTER TABLE tasks DROP COLUMN {column}")
                db.execute("ALTER TABLE events DROP COLUMN execution_id")
            if version < 3:
                for column in ("effective_model", "resolved_model"):
                    db.execute(f"ALTER TABLE tasks DROP COLUMN {column}")
            if version == 1:
                for column in ("transcript_path", "hook_seen_at"):
                    db.execute(f"ALTER TABLE tasks DROP COLUMN {column}")
            db.execute(f"PRAGMA user_version={version}")
        return store, task

    def test_v1_v2_upgrade_recovers_intent_and_metadata(self):
        for version in (1, 2):
            with self.subTest(version=version):
                old, task = self.legacy_store(version)
                migrated = Store(old.root)
                result = migrated.get(task["id"])
                self.assertEqual(result["model"], "sonnet")
                self.assertEqual(result["initial_model"], "haiku")
                self.assertIsNone(result["effective_model"])
                self.assertIsNone(result["observed_at"])
                self.assertEqual(result["resolved_model"], "sonnet")
                for field in ("config", "decision", "prompt_sha256", "prompt_chars", "created_at", "cwd"):
                    self.assertEqual(result[field], task[field])
                self.assertEqual(len(migrated.events(task["id"])), 3)
                with migrated.connect() as db:
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertNotIn(b"PRIVATE-MIGRATION-PROMPT", migrated.path.read_bytes())

    def test_migration_does_not_pin_auto_switch_within_same_family(self):
        old, task = self.legacy_store(2)
        with sqlite3.connect(old.path) as db:
            db.execute("DELETE FROM events WHERE task_id=? AND kind != 'created'", (task["id"],))
            for kind, model, source in (("SessionStart", "claude-haiku-original", "startup"),
                                        ("PostModelSwitch", "claude-haiku-fallback", "auto")):
                db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                           (task["id"], task["created_at"], kind, model, source))
            db.execute("UPDATE tasks SET model='claude-haiku-fallback' WHERE id=?", (task["id"],))
        migrated = Store(old.root).get(task["id"])
        self.assertEqual(migrated["model"], "haiku")
        self.assertEqual(migrated["resolved_model"], "claude-haiku-original")

    def test_v3_upgrade_keeps_choice_and_pin_without_stale_confirmation(self):
        old, task = self.legacy_store(3)
        with sqlite3.connect(old.path) as db:
            db.execute("UPDATE tasks SET model='sonnet',resolved_model='claude-sonnet-fixed',"
                       "effective_model='opus' WHERE id=?", (task["id"],))
        migrated = Store(old.root).get(task["id"])
        self.assertEqual(migrated["model"], "sonnet")
        self.assertEqual(migrated["resolved_model"], "claude-sonnet-fixed")
        self.assertIsNone(migrated["observed_at"])
        self.assertIsNone(migrated["effective_model"])

    def test_partial_migration_rolls_back_schema_and_data(self):
        old, task = self.legacy_store(2)
        with patch("claude_task_router.state.matches_choice", side_effect=RuntimeError("interrupted migration")):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                Store(old.root)
        with sqlite3.connect(old.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            self.assertNotIn("effective_model", columns)
            self.assertEqual(db.execute("SELECT model FROM tasks").fetchone()[0], "opus")
        self.assertEqual(Store(old.root).get(task["id"])["model"], "sonnet")

    def test_concurrent_fresh_initialization_and_v1_v2_migrations(self):
        for version in (0, 1, 2):
            with self.subTest(version=version):
                if version:
                    old, task = self.legacy_store(version)
                    root = old.root
                else:
                    root = self.root / "fresh"
                    root.mkdir()
                    task = None
                # Hold the write lock until every worker is attempting initialization.
                gate = sqlite3.connect(root / "tasks.sqlite3")
                gate.execute("BEGIN IMMEDIATE")
                workers = []
                ready_paths = []
                try:
                    for index in range(6):
                        ready = self.root / f"ready-{version}-{index}"
                        ready_paths.append(ready)
                        workers.append(subprocess.Popen([sys.executable, "-c", WORKER, str(root), str(ready)],
                            cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                    deadline = time.monotonic() + 5
                    while not all(path.exists() for path in ready_paths) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(all(path.exists() for path in ready_paths))
                    gate.rollback()
                    for worker in workers:
                        out, err = worker.communicate(timeout=10)
                        self.assertEqual(worker.returncode, 0, (out, err))
                    migrated = Store(root)
                    if task:
                        self.assertEqual(migrated.get(task["id"])["model"], "sonnet")
                    with migrated.connect() as db:
                        self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                        self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 6 + bool(task))
                        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
                finally:
                    gate.close()
                    for worker in workers:
                        if worker.poll() is None:
                            worker.kill()
                        worker.communicate(timeout=5)

    def test_future_schema_is_not_downgraded(self):
        store = Store(self.root / "future")
        with store.connect() as db:
            db.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(ValueError, "não suportado"):
            Store(store.root)
        with sqlite3.connect(store.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 999)
