"""End-to-end installer checks. Pip builds locally; Claude is always simulated."""

import os
import json
import signal
import importlib.util
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ctr install space ' ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.active = self.root / "venv with space '"
        self.bin_dir = self.root / "bin with space '"
        self.env = dict(os.environ, CTR_VENV_DIR=str(self.active), CTR_BIN_DIR=str(self.bin_dir),
                        XDG_CONFIG_HOME=str(self.root / "config"), PYTHONNOUSERSITE="1")
        self.env.pop("PYTHONPATH", None)
        self.env.pop("PYTHONHOME", None)

    def install(self, *args, env=None, code=0):
        result = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), *args],
                                cwd=self.root, env=env or self.env, text=True,
                                capture_output=True, timeout=180)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def smoke(self):
        result = subprocess.run([str(self.active / "bin/python"), str(ROOT / "tests/installed_smoke.py"),
                                 str(self.root / "workspace")], cwd=self.root, env=self.env,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clean_install_upgrade_failure_and_rollback_preserve_state(self):
        self.install()
        self.assertTrue((self.bin_dir / "ctr").is_symlink())
        first = self.active.resolve()
        self.smoke()
        db = self.root / "workspace/state/tasks.sqlite3"
        before = db.read_bytes()
        self.install()
        second = self.active.resolve()
        self.assertNotEqual(first, second)
        self.assertEqual(db.read_bytes(), before)  # Installer never opens state.
        self.smoke()
        before = db.read_bytes()
        # Build isolation cannot fetch setuptools: fail before activation.
        self.install(env=dict(self.env, PIP_NO_INDEX="1"), code=1)
        self.assertEqual(self.active.resolve(), second)
        self.assertEqual(db.read_bytes(), before)
        self.install("--rollback")
        self.assertEqual(self.active.resolve(), first)
        self.assertEqual(db.read_bytes(), before)
        self.smoke()
        with sqlite3.connect(db) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        ready = self.root / "native-ready"
        task = json.loads((self.root / "workspace/before.json").read_text())["id"]
        child = subprocess.Popen([str(self.bin_dir / "ctr"), "--state-dir", str(db.parent),
                                  "--claude-bin", str(self.root / "workspace/fake claude"), "resume", task],
                                 env=dict(self.env, FAKE_SLEEP="30", FAKE_READY=str(ready)),
                                 cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            # The installation lease protects even a state directory the
            # uninstall caller does not know about.
            self.install("--uninstall", "--state-dir", str(self.root / "unrelated-state"), code=1)
            self.assertTrue((self.bin_dir / "ctr").exists())
        finally:
            child.send_signal(signal.SIGTERM)
            child.communicate(timeout=10)
        self.assertEqual(child.returncode, 143)
        self.install("--uninstall", "--state-dir", str(self.root / "workspace/state"))
        self.assertFalse(self.active.exists())
        self.assertFalse((self.bin_dir / "ctr").exists())
        self.assertTrue(db.exists())
        self.assertTrue((self.root / "workspace/sessions").exists())

    def test_foreign_commands_environments_and_backups_are_preserved(self):
        self.bin_dir.mkdir()
        command = self.bin_dir / "ctr"
        for kind in ("file", "directory", "symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    command.write_text("foreign command")
                elif kind == "directory":
                    command.mkdir()
                else:
                    command.symlink_to(self.root / "missing-foreign-command")
                self.assertIn("outro comando", self.install(code=1).stderr)
                self.assertFalse(self.active.exists())
                if kind == "directory":
                    command.rmdir()
                else:
                    command.unlink()
        self.active.mkdir()
        marker = self.active / "foreign"
        marker.write_text("preserve me")
        self.assertIn("Ambiente alheio", self.install(code=1).stderr)
        self.assertEqual(marker.read_text(), "preserve me")
        shutil.rmtree(self.active)
        previous = self.active.with_name(self.active.name + ".previous")
        previous.write_text("foreign backup")
        self.assertIn("Backup alheio", self.install(code=1).stderr)
        self.assertEqual(previous.read_text(), "foreign backup")

    def test_legacy_real_venv_upgrade_and_rollback(self):
        # Reproduce the V0.1 layout (real venv, stable command symlink).
        subprocess.run([sys.executable, "-m", "venv", str(self.active)], check=True)
        result = subprocess.run([str(self.active / "bin/python"), "-m", "pip", "install",
                                 "--disable-pip-version-check", "--no-deps", str(ROOT)],
                                env=self.env, text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.bin_dir.mkdir()
        (self.bin_dir / "ctr").symlink_to(self.active / "bin/ctr")
        self.smoke()
        self.install()
        self.assertTrue(self.active.is_symlink())
        self.smoke()
        self.install("--rollback")
        self.smoke()  # Legacy shebang must still resolve via the stable name.

    def test_foreign_command_created_during_activation_is_never_replaced(self):
        spec = importlib.util.spec_from_file_location("ctr_installer", ROOT / "scripts/install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        self.bin_dir.mkdir()
        self.active.mkdir()
        (self.active / ".ctr-install").write_text(str(self.active))
        command = self.bin_dir / "ctr"
        real_exists = installer.exists

        def competing_command(path):
            # A foreign process wins creation between the last check and publish.
            if path == command and self.active.is_symlink():
                command.write_text("foreign command created concurrently")
                return False
            return real_exists(path)

        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(installer, "exists", side_effect=competing_command), \
             patch.object(installer.subprocess, "run"):
            with self.assertRaises(FileExistsError):
                installer.install()
        self.assertEqual(command.read_text(), "foreign command created concurrently")


if __name__ == "__main__":
    unittest.main()
