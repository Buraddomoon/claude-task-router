"""Prepare a complete venv before activation; retain the previous generation."""

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid


def absolute(raw):
    # Do not resolve the active symlink: its name must remain stable on upgrade.
    return Path(os.path.abspath(Path(raw).expanduser()))


def exists(path):
    return path.exists() or path.is_symlink()


def link(target, destination):
    temporary = destination.with_name(destination.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def check_command(command, active):
    if exists(command) and (not command.is_symlink() or os.readlink(command) != str(active / "bin/ctr")):
        raise ValueError(f"Já existe outro comando em {command}. Use CTR_BIN_DIR para escolher outro diretório.")


def owned(path, active):
    marker = path / ".ctr-install"
    return marker.is_file() and marker.read_text() == str(active)


def legacy(path):
    entry = path / "bin/ctr"
    return (path.is_dir() and not path.is_symlink() and (path / "pyvenv.cfg").is_file()
            and entry.is_file() and "from claude_task_router.cli import main" in entry.read_text())


def install(rollback=False):
    if sys.version_info < (3, 11):
        raise ValueError("Requer Python 3.11+")
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    active = absolute(os.environ.get("CTR_VENV_DIR", data / "claude-task-router/venv"))
    bin_dir = absolute(os.environ.get("CTR_BIN_DIR", Path.home() / ".local/bin"))
    command = bin_dir / "ctr"
    previous = active.with_name(active.name + ".previous")
    check_command(command, active)
    active.parent.mkdir(parents=True, exist_ok=True)
    # Serialize installers without touching the task database or its locks.
    with active.with_name(active.name + ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_command(command, active)
        if exists(active) and not (owned(active, active) or legacy(active)):
            raise ValueError(f"Ambiente alheio em {active}; escolha outro CTR_VENV_DIR.")
        if exists(previous) and not (previous.is_symlink() and owned(previous, active)):
            raise ValueError(f"Backup alheio em {previous}; escolha outro CTR_VENV_DIR.")
        if rollback:
            if not active.is_symlink() or not previous.is_symlink() or not previous.exists():
                raise ValueError("Não há instalação anterior disponível para rollback.")
            old = active.resolve()
            target = previous.resolve()
            link(target, active)
            link(old, previous)
        else:
            generations = active.with_name(active.name + ".releases")
            generations.mkdir(exist_ok=True)
            candidate = Path(tempfile.mkdtemp(prefix="release-", dir=generations))
            activated = False
            try:
                subprocess.run([sys.executable, "-m", "venv", str(candidate)], check=True)
                subprocess.run([str(candidate / "bin/python"), "-m", "pip", "install",
                                "--disable-pip-version-check", "--no-deps",
                                str(Path(__file__).resolve().parent.parent)], check=True)
                subprocess.run([str(candidate / "bin/ctr"), "--version"], check=True,
                               cwd=candidate, stdout=subprocess.DEVNULL)
                (candidate / ".ctr-install").write_text(str(active))
                bin_dir.mkdir(parents=True, exist_ok=True)
                check_command(command, active)
                old = None
                if active.is_symlink():
                    old = active.resolve()
                elif active.exists():
                    # Older installers created a real venv at the active name.
                    # Its shebang still uses that name and works after rollback.
                    old = generations / ("legacy-" + uuid.uuid4().hex)
                    active.rename(old)
                    (old / ".ctr-install").write_text(str(active))
                try:
                    link(candidate, active)
                except OSError:
                    if old is not None and not exists(active):
                        link(old, active)
                    raise
                activated = True
                if old is not None:
                    link(old, previous)
            finally:
                if not activated:
                    shutil.rmtree(candidate)
        bin_dir.mkdir(parents=True, exist_ok=True)
        check_command(command, active)
        link(active / "bin/ctr", command)
    print(f"{'Rollback concluído' if rollback else 'Instalado'}: {command}")
    print(f"Se necessário, adicione {bin_dir} ao PATH. Verifique com: ctr doctor")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollback", action="store_true", help="Reativar a geração anterior sem alterar o banco")
    args = parser.parse_args()
    try:
        install(args.rollback)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Instalação não concluída: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
