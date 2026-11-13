"""Private POSIX storage; reject symlinks, hardlinks and special files."""

import os
from pathlib import Path
import stat


def private_directory(path):
    path = Path(path).expanduser().absolute()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid():
            raise ValueError("Diretório de estado deve pertencer ao usuário atual.")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return path.resolve()


def private_file(path, flags=os.O_CREAT | os.O_RDWR):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError("Arquivo privado deve ser regular, sem hardlinks e pertencer ao usuário atual.")
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd
