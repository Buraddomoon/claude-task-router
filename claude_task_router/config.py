"""Explicit user configuration; project files are never auto-executed or loaded."""

from dataclasses import asdict, dataclass, field
import json
import os
import re
from pathlib import Path

TIERS = ("economy", "balanced", "advanced")
MAX_PROMPT_BYTES = 256 * 1024


def validate_model(model: str) -> str:
    if (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\[\]-]{0,511}", model)
            or model.lower().startswith(("sk-ant-", "sk-proj-"))):
        raise ValueError("Modelo deve ser alias ou ID ASCII estável, com até 512 caracteres; não informe credenciais.")
    if model.lower().split("[")[0] in {"default", "opusplan", "best"}:
        raise ValueError("Use um modelo estável: haiku, sonnet, opus ou ID explícito.")
    return model


@dataclass
class Config:
    models: dict[str, str] = field(default_factory=lambda: dict(
        economy="haiku", balanced="sonnet", advanced="opus"))
    min_tier: str = "economy"
    medium_words: int = 450
    long_words: int = 1400
    scan_chars: int = 65536

    def __post_init__(self):
        if not isinstance(self.models, dict) or set(self.models) != set(TIERS):
            raise ValueError("models deve conter exatamente economy, balanced e advanced.")
        for model in self.models.values():
            validate_model(model)
        if self.min_tier not in TIERS:
            raise ValueError("min_tier inválido.")
        for name in ("medium_words", "long_words", "scan_chars"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} deve ser inteiro positivo.")
        if not 100 <= self.scan_chars <= MAX_PROMPT_BYTES:
            raise ValueError("scan_chars deve estar entre 100 e 262144.")
        if self.medium_words >= self.long_words:
            raise ValueError("medium_words deve ser menor que long_words.")

    def snapshot(self):
        return asdict(self)


def config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "claude-task-router" / "config.json"


def load_config(path: Path | None = None) -> Config:
    source = path or config_path()
    if not source.exists() and path is None:
        return Config()
    if source.stat().st_size > 65536:
        raise ValueError("Configuração excede 64 KiB.")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuração deve ser um objeto JSON.")
    unknown = set(data) - set(Config.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Campos desconhecidos: {', '.join(sorted(unknown))}")
    return Config(**data)
