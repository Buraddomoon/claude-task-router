"""Private metadata and short SQLite transactions; POSIX task execution locks."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .config import validate_model


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def default_state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "claude-task-router"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or default_state_dir()).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "tasks.sqlite3"
        # Create privately before SQLite ever writes task metadata.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"Banco de versão {version} não suportado.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, cwd TEXT NOT NULL, model TEXT NOT NULL,
                    initial_model TEXT NOT NULL, tier TEXT NOT NULL,
                    decision_json TEXT NOT NULL, config_json TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL, prompt_chars INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_launched_at TEXT, observed_at TEXT,
                    launches INTEGER NOT NULL DEFAULT 0, last_exit_code INTEGER
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    at TEXT NOT NULL, kind TEXT NOT NULL, model TEXT, source TEXT
                );
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, cwd: Path, prompt: str, decision: dict, config: dict) -> dict:
        task_id = str(uuid.uuid4())
        model = validate_model(decision["model"])
        timestamp = now()
        with self.connect() as db:
            db.execute("""INSERT INTO tasks
                (id,cwd,model,initial_model,tier,decision_json,config_json,prompt_sha256,
                 prompt_chars,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, str(cwd.resolve()), model, model, decision["tier"],
                 json.dumps(decision), json.dumps(config),
                 hashlib.sha256(prompt.encode()).hexdigest(), len(prompt), timestamp, timestamp))
            db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                       (task_id, timestamp, "created", model, decision["policy"]))
        return self.get(task_id)

    def get(self, ref: str, cwd: Path | None = None) -> dict:
        with self.connect() as db:
            if ref == "latest":
                rows = db.execute("""SELECT * FROM tasks WHERE cwd = ?
                    ORDER BY COALESCE(last_launched_at, created_at) DESC LIMIT 1""",
                    (str((cwd or Path.cwd()).resolve()),)).fetchall()
            else:
                if not re.fullmatch(r"[0-9a-f-]{8,36}", ref):
                    raise ValueError("Use UUID, prefixo de pelo menos 8 caracteres ou latest.")
                rows = db.execute("SELECT * FROM tasks WHERE id LIKE ? LIMIT 2", (ref + "%",)).fetchall()
        if not rows:
            raise ValueError("Tarefa não encontrada no roteador.")
        if len(rows) != 1:
            raise ValueError("Prefixo ambíguo; use o UUID completo.")
        task = dict(rows[0])
        task["decision"] = json.loads(task.pop("decision_json"))
        task["config"] = json.loads(task.pop("config_json"))
        return task

    def list_tasks(self, cwd: Path, all_projects=False, limit=20) -> list[dict]:
        where, args = ("", ()) if all_projects else ("WHERE cwd = ?", (str(cwd.resolve()),))
        with self.connect() as db:
            rows = db.execute(f"""SELECT id,cwd,model,tier,created_at,updated_at,
                last_launched_at,last_exit_code,observed_at FROM tasks {where}
                ORDER BY COALESCE(last_launched_at,created_at) DESC LIMIT ?""", (*args, limit)).fetchall()
        return [dict(row) for row in rows]

    def events(self, task_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT at,kind,model,source FROM events WHERE task_id=? ORDER BY id",
                              (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_model(self, task_id: str, model: str, source="manual"):
        model = validate_model(model)
        timestamp = now()
        with self.connect() as db:
            changed = db.execute("UPDATE tasks SET model=?,updated_at=?,observed_at=NULL WHERE id=?",
                                 (model, timestamp, task_id)).rowcount
            if changed != 1:
                raise ValueError("Tarefa não encontrada.")
            db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                       (task_id, timestamp, "model_requested", model, source))

    def observe(self, payload: dict) -> bool:
        event = payload.get("hook_event_name")
        if event not in {"SessionStart", "PostModelSwitch"}:
            return False
        model = payload.get("model") if event == "SessionStart" else payload.get("to_model")
        if not model:
            return False
        validate_model(model)
        source = payload.get("source")
        if source not in {"startup", "resume", "compact", "clear", "fork", "command", "picker", "sdk", "auto"}:
            return False
        task_id = payload.get("session_id")
        cwd = payload.get("cwd")
        if not isinstance(task_id, str) or not isinstance(cwd, str):
            return False
        timestamp = now()
        with self.connect() as db:
            row = db.execute("SELECT cwd FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or Path(cwd).resolve() != Path(row["cwd"]):
                return False
            db.execute("UPDATE tasks SET model=?,updated_at=?,observed_at=? WHERE id=?",
                       (model, timestamp, timestamp, task_id))
            db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                       (task_id, timestamp, event, model, source))
        return True

    def launched(self, task_id: str):
        timestamp = now()
        with self.connect() as db:
            db.execute("UPDATE tasks SET launches=launches+1,last_launched_at=?,updated_at=? WHERE id=?",
                       (timestamp, timestamp, task_id))

    def finished(self, task_id: str, exit_code: int):
        with self.connect() as db:
            db.execute("UPDATE tasks SET last_exit_code=?,updated_at=? WHERE id=?",
                       (exit_code, now(), task_id))

    @contextmanager
    def task_lock(self, task_id: str):
        # Full UUID validation before using IDs as filenames.
        if str(uuid.UUID(task_id)) != task_id:
            raise ValueError("UUID inválido.")
        directory = self.root / "locks"
        directory.mkdir(exist_ok=True, mode=0o700)
        fd = os.open(directory / f"{task_id}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Tarefa já está em execução em outro processo.") from exc
            yield
        finally:
            os.close(fd)
