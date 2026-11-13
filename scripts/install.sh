#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${CTR_VENV_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/claude-task-router/venv}"
BIN_DIR="${CTR_BIN_DIR:-$HOME/.local/bin}"

if [[ -e "$BIN_DIR/ctr" || -L "$BIN_DIR/ctr" ]]; then
  if [[ "$(readlink "$BIN_DIR/ctr" || true)" != "$VENV_DIR/bin/ctr" ]]; then
    echo "Já existe outro comando em $BIN_DIR/ctr. Use CTR_BIN_DIR para escolher outro diretório." >&2
    exit 1
  fi
fi
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Requer Python 3.11+"'
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-deps "$REPO_ROOT"
mkdir -p "$BIN_DIR"
ln -sfn "$VENV_DIR/bin/ctr" "$BIN_DIR/ctr"
echo "Instalado: $BIN_DIR/ctr"
echo "Se necessário, adicione $BIN_DIR ao PATH. Verifique com: ctr doctor"
