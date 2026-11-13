"""Remove only managed generations; user state and Claude are never deleted."""

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import shutil
import sys

from .privacy import private_file


def remove_installation(active=None, bin_dir=None, state_dir=None):
    from .state import Store, default_state_dir
    if active is None:
        marker = Path(sys.prefix) / ".ctr-install"
        data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        active = marker.read_text() if marker.is_file() else os.environ.get("CTR_VENV_DIR", data / "claude-task-router/venv")
    active = Path(os.path.abspath(Path(active).expanduser()))
    bin_dir = Path(os.path.abspath(Path(bin_dir or os.environ.get("CTR_BIN_DIR", Path.home() / ".local/bin")).expanduser()))
    command = bin_dir / "ctr"
    previous = active.with_name(active.name + ".previous")
    releases = active.with_name(active.name + ".releases")

    def exists(path):
        return path.exists() or path.is_symlink()

    def owned(path):
        return (path.is_dir() and (path / ".ctr-install").is_file()
                and (path / ".ctr-install").read_text() == str(active))

    if exists(command) and (not command.is_symlink() or os.readlink(command) != str(active / "bin/ctr")):
        raise ValueError("Comando alheio: desinstalação recusada. Informe --bin-dir correto.")
    if not exists(active):
        return dict(installed=False, removed_generations=0, state_preserved=True)
    if not active.is_symlink() or not owned(active) or releases.is_symlink() or not releases.is_dir():
        raise ValueError("Instalação sem marcador gerenciado; use o gerenciador original, sem remoção automática.")
    if active.resolve().parent != releases.resolve():
        raise ValueError("Geração ativa fora da árvore gerenciada; nada foi removido.")
    if exists(previous) and (not previous.is_symlink() or not owned(previous)
                             or previous.resolve().parent != releases.resolve()):
        raise ValueError("Backup alheio ou inválido; nada foi removido.")
    generations = [p for p in releases.iterdir() if not p.is_symlink() and owned(p)]
    with os.fdopen(private_file(active.with_name(active.name + ".install.lock")), "a") as lock, ExitStack() as stack:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        root = Path(state_dir or default_state_dir()).expanduser()
        if (root / "tasks.sqlite3").exists():
            store = Store(root)
            with store.connect() as db:
                ids = [row[0] for row in db.execute("SELECT id FROM tasks")]
            for task_id in ids:
                stack.enter_context(store.task_lock(task_id))
        # All ownership/known-task locks are checked before deleting anything.
        if exists(command):
            if not command.is_symlink() or os.readlink(command) != str(active / "bin/ctr"):
                raise ValueError("Comando alterado durante desinstalação; nada foi removido.")
            command.unlink()
        active.unlink()
        if exists(previous):
            previous.unlink()
        for generation in generations:
            shutil.rmtree(generation)
        try:
            releases.rmdir()
        except OSError:
            pass  # Unrecognized contents are preserved.
    return dict(installed=True, removed_generations=len(generations), state_preserved=True,
                config_preserved=True, claude_untouched=True)
