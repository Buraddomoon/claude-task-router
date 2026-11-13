from contextlib import redirect_stdout, redirect_stderr
import io
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

from claude_task_router.cli import main
from claude_task_router.classifier import classify
from claude_task_router.maintenance import backup_state, configure, restore_state
from claude_task_router.state import Store


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_setup_validates_and_preserves_existing_configuration(self):
        path = self.root / "config.json"
        first = configure(path, dict(min_tier="balanced"))
        self.assertTrue(first["created"])
        original = path.read_bytes()
        self.assertFalse(configure(path)["created"])
        with self.assertRaises(ValueError):
            configure(path, dict(min_tier="economy"))
        with self.assertRaises(ValueError):
            configure(path, dict(economy="--invalid"), force=True)
        self.assertEqual(path.read_bytes(), original)
        changed = configure(path, dict(min_tier="advanced"), force=True)
        self.assertEqual(Path(changed["backup"]).read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())["min_tier"], "advanced")

    def test_snapshot_backup_restore_and_no_overwrite(self):
        source = Store(self.root / "state")
        task = source.create(self.root, "Fix typo PRIVATE-BACKUP-PROMPT", classify("Fix typo").to_dict(), {})
        source.set_model(task["id"], "opus")
        backup = self.root / "backup.sqlite3"
        backup_state(source, backup)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        source.set_model(task["id"], "sonnet")
        restored_root = self.root / "restored"
        result = restore_state(backup, restored_root)
        self.assertTrue(result["integrity_ok"])
        self.assertEqual(Store(restored_root).get(task["id"])["model"], "opus")
        self.assertEqual(source.get(task["id"])["model"], "sonnet")
        with self.assertRaises(FileExistsError):
            backup_state(source, backup)
        with self.assertRaises(FileExistsError):
            restore_state(backup, source.root)
        self.assertNotIn(b"PRIVATE-BACKUP-PROMPT", backup.read_bytes())

    def test_cli_setup_and_backup_restore_without_claude(self):
        config = self.root / "settings.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", str(config), "setup"]), 0)
            self.assertEqual(main(["--state-dir", str(self.root / "state"), "backup", str(self.root / "snapshot")]), 0)
            self.assertEqual(main(["--state-dir", str(self.root / "recovered"), "restore", str(self.root / "snapshot")]), 0)

    def test_restore_rejects_future_or_unrelated_database_before_creating_state(self):
        for version in (4, 99):
            path = self.root / f"invalid-{version}"
            with sqlite3.connect(path) as db:
                db.execute(f"PRAGMA user_version={version}")
            destination = self.root / f"destination-{version}"
            with self.assertRaises(ValueError):
                restore_state(path, destination)
            self.assertFalse(destination.exists())
