"""Explicit local setup, consistent backups and safe restore."""

import json
import os
from pathlib import Path
import sqlite3
import uuid

from .config import Config, config_path, load_config
from .privacy import private_directory, private_file


def configure(path=None, overrides=None, force=False, binary="claude", check_models=False):
    path = (path or config_path()).expanduser().absolute()
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    current = load_config(path) if path.exists() else Config()
    if path.exists() and overrides and not force:
        raise ValueError("Configuração existente; use setup --force para alterar e guardar backup.")
    data = current.snapshot()
    for tier in ("economy", "balanced", "advanced"):
        if tier in overrides:
            data["models"][tier] = overrides[tier]
    if "min_tier" in overrides:
        data["min_tier"] = overrides["min_tier"]
    selected = Config(**data)
    if check_models:
        from .models import inspect_model
        for model in dict.fromkeys(selected.models.values()):
            result, code = inspect_model(binary, model)
            if code:
                raise ValueError(f"Modelo não confirmado pelo CLI: {model} ({result['status']}). Configuração preservada.")
    if path.exists() and not force:
        return dict(created=False, path=str(path), config=current.snapshot())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = None
    if path.exists():
        fd = private_file(path, os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            previous = stream.read(65537)
        backup = path.with_name(path.name + ".backup-" + uuid.uuid4().hex)
        with os.fdopen(private_file(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY), "wb") as stream:
            stream.write(previous)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with os.fdopen(private_file(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY), "w") as stream:
            json.dump(selected.snapshot(), stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, path)
        else:
            # Exclusive publication: never replace a concurrently created config.
            os.link(temporary, path)
            temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)
    return dict(created=True, path=str(path), backup=str(backup) if backup else None, config=selected.snapshot())


def backup_state(store, destination):
    destination = destination.expanduser().absolute()
    os.close(private_file(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR))
    try:
        target = sqlite3.connect(destination)
        try:
            with store.connect() as source:
                source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup não passou na verificação de integridade.")
        finally:
            target.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return dict(path=str(destination), schema=4, contains_private_metadata=True)


def restore_state(backup, root):
    from .state import Store
    backup = backup.expanduser().absolute()
    # Validate the input as a regular owned file before SQLite opens it.
    os.close(private_file(backup, os.O_RDONLY))
    source = sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup inválido.")
        version = source.execute("PRAGMA user_version").fetchone()[0]
        if version not in {1, 2, 3, 4}:
            raise ValueError("Schema do backup não suportado; não será rebaixado.")
        required_tasks = {"id", "cwd", "model", "initial_model", "tier", "decision_json", "config_json",
                          "prompt_sha256", "prompt_chars", "created_at", "updated_at", "last_launched_at",
                          "observed_at", "launches", "last_exit_code"}
        if version >= 2:
            required_tasks.update({"transcript_path", "hook_seen_at"})
        if version >= 3:
            required_tasks.update({"effective_model", "resolved_model"})
        if version >= 4:
            required_tasks.update({"execution_id", "finished_at", "choice_revision", "choice_changed_at"})
        required_events = {"id", "task_id", "at", "kind", "model", "source"}
        if version >= 4:
            required_events.add("execution_id")
        for table, required in (("tasks", required_tasks), ("events", required_events)):
            actual = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
            if not required <= actual:
                raise ValueError("Backup sem estrutura válida do roteador.")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Backup com referências inconsistentes.")
        root = private_directory(root)
        destination = root / "tasks.sqlite3"
        # A live or existing database is never replaced by restore.
        os.close(private_file(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR))
        try:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
            restored = Store(root)
            return restored.diagnostics()
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    finally:
        source.close()
