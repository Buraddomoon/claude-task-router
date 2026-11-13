"""Bounded deterministic PT/EN rules. No network, model invocation or repo scan."""

from dataclasses import asdict, dataclass
import re
import unicodedata

from .config import Config, MAX_PROMPT_BYTES, TIERS


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


RULES = (
    ("high_risk", 6, re.compile(
        r"\b(authenticat\w*|autentic\w*|authoriz\w*|autoriz\w*|oauth|jwt|"
        r"cryptograph\w*|criptograf\w*|payment\w*|pagamento\w*|"
        r"security audit|auditoria de seguranca|vulnerabil\w*|"
        r"migrac\w* de (?:dados|banco)|database migration|data migration|"
        r"production incident|incidente em producao)\b")),
    ("complex_reasoning", 6, re.compile(
        r"\b(arquitet\w*|architect\w*|distributed\s+system\w*|sistemas? distribuidos?|"
        r"race condition\w*|condic\w* de corrida|deadlock\w*|"
        r"intermittent\w*|intermitente\w*|root cause|causa raiz|"
        r"redesign|reestrutur\w*|threat model\w*)\b")),
    ("broad_scope", 3, re.compile(
        r"\b(refator\w*|refactor\w*|multi[- ]?(?:service|repo|module)\w*|"
        r"varios (?:servicos|modulos)|ponta a ponta|end[- ]to[- ]end|"
        r"aplicac\w* completa|complete (?:app|application|system))\b")),
    ("implementation", 2, re.compile(
        r"\b(implement\w*|desenvolv\w*|build|feature\w*|funcionalidade\w*|"
        r"crie|criar|create|adicione|adicionar|add|bug\w*|endpoint\w*)\b")),
)
TRIVIAL = re.compile(
    r"\b(typo\w*|ortograf\w*|spelling|renome\w*|rename|"
    r"tradu\w*|translat\w*|formate|formatar|format|"
    r"resuma|resumir|summari\w*|explique (?:este|esse|o) comando|"
    r"explain (?:this|the) command)\b")
PATHS = re.compile(r"(?<!\w)(?:[\w.-]+/)+[\w.-]+|\b[\w-]+\.(?:py|js|ts|tsx|jsx|go|rs|md|json|yaml)\b")


@dataclass(frozen=True)
class Decision:
    tier: str
    model: str
    score: int
    reasons: tuple[str, ...]
    scanned_chars: int
    total_chars: int
    policy: str = "local-rules-v1"

    def to_dict(self):
        return asdict(self)


def validate_prompt(prompt: str) -> str:
    if not prompt.strip():
        raise ValueError("A tarefa inicial não pode estar vazia.")
    if "\x00" in prompt:
        raise ValueError("Prompt não pode conter NUL.")
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError("Prompt excede 256 KiB; use referências a arquivos.")
    return prompt


def classify(prompt: str, config: Config | None = None) -> Decision:
    config = config or Config()
    validate_prompt(prompt)
    text = normalize(prompt[:config.scan_chars])
    words = len(text.split())
    reasons = []
    score = 0
    for reason, weight, pattern in RULES:
        if pattern.search(text):
            reasons.append(reason)
            score += weight
    paths = len(set(PATHS.findall(text)))
    if paths >= 4:
        reasons.append("many_files")
        score += 3
    if words >= config.long_words:
        reasons.append("long_specification")
        score += 4
    elif words >= config.medium_words:
        reasons.append("medium_specification")
        score += 2
    truncated = len(prompt) > config.scan_chars
    if truncated:
        reasons.append("scan_limit_reached")
    if score >= 6:
        tier = "advanced"
    elif score == 0 and TRIVIAL.search(text) and words <= 100 and paths <= 2 and not truncated:
        tier = "economy"
        reasons.append("bounded_simple_intent")
    else:
        tier = "balanced"
        if not reasons:
            reasons.append("uncertain_use_balanced")
    if TIERS.index(tier) < TIERS.index(config.min_tier):
        tier = config.min_tier
        reasons.append("configured_minimum")
    return Decision(tier, config.models[tier], score, tuple(reasons),
                    min(len(prompt), config.scan_chars), len(prompt))
