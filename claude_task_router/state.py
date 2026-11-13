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


def matches_choice(choice: str, model: str) -> bool:
    """Only pin recognized aliases to their own family; custom IDs stay literal."""
    return model == choice or (choice in {"haiku", "sonnet", "opus", "fable"}
                               and model.startswith(f"claude-{choice}-"))


def launch_model(task: dict) -> str:
    return task.get("resolved_model") or task["model"]


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
            if version not in (0, 1, 2, 3, 4):
                raise ValueError(f"Banco de versão {version} não suportado.")
            if version == 1:
                db.execute("ALTER TABLE tasks ADD COLUMN transcript_path TEXT")
                db.execute("ALTER TABLE tasks ADD COLUMN hook_seen_at TEXT")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, cwd TEXT NOT NULL, model TEXT NOT NULL,
                    initial_model TEXT NOT NULL, tier TEXT NOT NULL,
                    decision_json TEXT NOT NULL, config_json TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL, prompt_chars INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    last_launched_at TEXT, observed_at TEXT, transcript_path TEXT, hook_seen_at TEXT,
                    launches INTEGER NOT NULL DEFAULT 0, last_exit_code INTEGER
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    at TEXT NOT NULL, kind TEXT NOT NULL, model TEXT, source TEXT
                );
            """)
            if version < 3:
                db.execute("ALTER TABLE tasks ADD COLUMN effective_model TEXT")
                db.execute("ALTER TABLE tasks ADD COLUMN resolved_model TEXT")
                # Recover intent from metadata, rather than promoting an old auto switch.
                for row in db.execute("SELECT id,model,initial_model,observed_at FROM tasks").fetchall():
                    choice = row["initial_model"]
                    for event in db.execute("SELECT kind,model,source FROM events WHERE task_id=? ORDER BY id",
                                            (row["id"],)).fetchall():
                        if event["model"] and (event["kind"] == "model_requested" or
                                (event["kind"] == "PostModelSwitch" and event["source"] in
                                 {"command", "picker", "sdk"})):
                            choice = event["model"]
                    effective = row["model"] if row["observed_at"] else None
                    resolved = effective if effective and matches_choice(choice, effective) else None
                    db.execute("UPDATE tasks SET model=?,effective_model=?,resolved_model=? WHERE id=?",
                               (choice, effective, resolved, row["id"]))
                db.execute("PRAGMA user_version = 3")
            if version < 4:
                for column in ("execution_id TEXT", "finished_at TEXT",
                               "choice_revision INTEGER NOT NULL DEFAULT 0", "choice_changed_at TEXT"):
                    db.execute(f"ALTER TABLE tasks ADD COLUMN {column}")
                db.execute("ALTER TABLE events ADD COLUMN execution_id TEXT")
                # Legacy observations have no execution identity.
                db.execute("UPDATE tasks SET observed_at=NULL,effective_model=NULL,hook_seen_at=NULL")
                db.execute("PRAGMA user_version = 4")

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
            rows = db.execute(f"""SELECT id,cwd,model,effective_model,resolved_model,tier,created_at,updated_at,
                last_launched_at,last_exit_code,observed_at,execution_id FROM tasks {where}
                ORDER BY COALESCE(last_launched_at,created_at) DESC LIMIT ?""", (*args, limit)).fetchall()
        return [dict(row) for row in rows]

    def events(self, task_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT at,kind,model,source,execution_id FROM events WHERE task_id=? ORDER BY id",
                              (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_model(self, task_id: str, model: str, source="manual"):
        model = validate_model(model)
        timestamp = now()
        with self.connect() as db:
            changed = db.execute("""UPDATE tasks SET model=?,updated_at=?,observed_at=NULL,
                                 effective_model=NULL,resolved_model=NULL,
                                 choice_revision=choice_revision+1,choice_changed_at=? WHERE id=?""",
                                 (model, timestamp, timestamp, task_id)).rowcount
            if changed != 1:
                raise ValueError("Tarefa não encontrada.")
            db.execute("INSERT INTO events(task_id,at,kind,model,source) VALUES(?,?,?,?,?)",
                       (task_id, timestamp, "model_requested", model, source))

    def observe(self, payload: dict, execution_id: str | None = None) -> bool:
        event = payload.get("hook_event_name")
        if event not in {"SessionStart", "PostModelSwitch"}:
            return False
        model = payload.get("model") if event == "SessionStart" else payload.get("to_model")
        if model:
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
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if (not row or not execution_id or row["execution_id"] != execution_id
                    or row["finished_at"] or row["updated_at"] > timestamp
                    or Path(cwd).resolve() != Path(row["cwd"])):
                return False
            # A delayed startup payload cannot undo a switch already observed.
            if event == "SessionStart" and row["observed_at"]:
                return False
            transcript = self.valid_transcript(payload.get("transcript_path"), task_id)
            db.execute("""UPDATE tasks SET hook_seen_at=?,
                transcript_path=COALESCE(?,transcript_path) WHERE id=?""",
                       (timestamp, str(transcript) if transcript else None, task_id))
            if model:
                choice = row["model"]
                resolved = row["resolved_model"]
                if event == "PostModelSwitch" and source in {"command", "picker", "sdk"}:
                    requested = payload.get("requested_model") or model
                    choice = validate_model(requested)
                    resolved = None
                    db.execute("""UPDATE tasks SET choice_revision=choice_revision+1,
                               choice_changed_at=? WHERE id=?""", (timestamp, task_id))
                target = resolved or choice
                compatible = matches_choice(target, model)
                if source != "auto" and compatible and not resolved:
                    resolved = model
                db.execute("""UPDATE tasks SET model=?,resolved_model=?,effective_model=?,
                           updated_at=?,observed_at=? WHERE id=?""",
                           (choice, resolved, model, timestamp, timestamp, task_id))
                if source == "auto" or not compatible:
                    db.execute("INSERT INTO events(task_id,at,kind,model,source,execution_id) VALUES(?,?,?,?,?,?)",
                               (task_id, timestamp, "model_diverged", model, source, execution_id))
            elif event == "PostModelSwitch":
                db.execute("UPDATE tasks SET effective_model=NULL,observed_at=NULL WHERE id=?", (task_id,))
            db.execute("INSERT INTO events(task_id,at,kind,model,source,execution_id) VALUES(?,?,?,?,?,?)",
                       (task_id, timestamp, event, model, source, execution_id))
        return True

    @staticmethod
    def valid_transcript(raw, task_id: str) -> Path | None:
        if not isinstance(raw, str):
            return None
        path = Path(raw).expanduser().resolve()
        config_root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser().resolve()
        if path.name != task_id + ".jsonl" or not path.is_relative_to(config_root / "projects"):
            return None
        return path

    def reconcile_transcript(self, task_id: str) -> bool:
        """Resolve absent SessionStart.model using at most the last 1 MiB on disk.

        Never override an observed model switch or reuse a response from a prior run.
        """
        task = self.get(task_id)
        if task["observed_at"] or not task["execution_id"] or not task["hook_seen_at"]:
            return False
        path = self.valid_transcript(task["transcript_path"], task_id)
        if not path or not path.is_file():
            return False
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - 1024 * 1024)
            stream.seek(start)
            tail = stream.read(1024 * 1024)
        if start:
            tail = tail.partition(b"\n")[2]
        for line in reversed(tail.splitlines()):
            try:
                entry = json.loads(line)
                if (not isinstance(entry, dict) or entry.get("type") != "assistant"
                        or entry.get("sessionId") != task_id):
                    continue
                at = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
                lower = max(task["last_launched_at"], task["choice_changed_at"] or "", task["hook_seen_at"])
                upper = task["finished_at"] or now()
                if not datetime.fromisoformat(lower) <= at <= datetime.fromisoformat(upper):
                    continue
                model = entry["message"]["model"]
                if not model or model.startswith("<"):
                    continue
                validate_model(model)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            timestamp = now()
            with self.connect() as db:
                # Compare-and-set avoids racing a late PostModelSwitch hook.
                target = launch_model(task)
                compatible = matches_choice(target, model)
                resolved = model if compatible else task["resolved_model"]
                changed = db.execute("""UPDATE tasks SET effective_model=?,resolved_model=?,observed_at=?,updated_at=?
                    WHERE id=? AND observed_at IS NULL AND model=? AND execution_id=?
                    AND choice_revision=?""",
                    (model, resolved, timestamp, timestamp, task_id, task["model"],
                     task["execution_id"], task["choice_revision"])).rowcount
                if changed:
                    db.execute("INSERT INTO events(task_id,at,kind,model,source,execution_id) VALUES(?,?,?,?,?,?)",
                               (task_id, timestamp, "model_resolved", model, "transcript_tail", task["execution_id"]))
                    if not compatible:
                        db.execute("INSERT INTO events(task_id,at,kind,model,source,execution_id) VALUES(?,?,?,?,?,?)",
                                   (task_id, timestamp, "model_diverged", model, "transcript_tail", task["execution_id"]))
            return bool(changed)
        return False

    def launched(self, task_id: str):
        timestamp = now()
        execution_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("""UPDATE tasks SET launches=launches+1,last_launched_at=?,updated_at=?,
                       execution_id=?,finished_at=NULL,last_exit_code=NULL,observed_at=NULL,
                       effective_model=NULL,hook_seen_at=NULL,transcript_path=NULL WHERE id=?""",
                       (timestamp, timestamp, execution_id, task_id))
        return execution_id

    def finished(self, task_id: str, exit_code: int):
        timestamp = now()
        with self.connect() as db:
            db.execute("UPDATE tasks SET last_exit_code=?,updated_at=?,finished_at=? WHERE id=?",
                       (exit_code, timestamp, timestamp, task_id))

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
