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
        r"redesign|reestrutur\w*|threat model\w*|consens\w*|quorum|"
        r"leader election|eleicao de lider|tolerancia a falhas)\b")),
    ("broad_scope", 3, re.compile(
        r"\b(refator\w*|refactor\w*|multi[- ]?(?:service|repo|module)\w*|"
        r"varios (?:servicos|modulos)|ponta a ponta|end[- ]to[- ]end|"
        r"aplicac\w* completa|complete (?:app|application|system))\b")),
    ("implementation", 2, re.compile(
        r"\b(implement\w*|desenvolv\w*|build|feature\w*|funcionalidade\w*|"
        r"crie|criar|create|adicione|adicionar|add|bug\w*|endpoint\w*)\b")),
)
PATHS = re.compile(r"(?<!\w)(?:[\w.-]+/)+[\w.-]+|\b[\w-]+\.(?:py|js|ts|tsx|jsx|go|rs|md|json|yaml)\b")
QUOTED = re.compile(r'```[\s\S]*?(?:```|$)|`[^`\n]*`|"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\'[^\'\n]*\'(?!\w)')
CLAUSES = re.compile(r"[.;!?\n]+|,\s*|\s+(?:e|and|then|while|enquanto|depois|tambem|also|plus|"
                     r"alem de|bem como|as well as|mas|but|porem|however)\s+")
NEGATIVE = re.compile(
    r"\b(?:nao|do not|don't|never|nunca|sem|without)\s+"
    r"(?:alter\w*|mud\w*|implement\w*|modifi\w*|renom\w*|rename|change|changing|"
    r"touch\w*|fix|corrij\w*)\b.*$")
SIMPLE_ACTION = re.compile(
    r"^(?:(?:please|por favor)\s+)?(?:"
    r"(?:fix|correct|corrij\w*|revise)\s+(?:(?:the|a|o|os|as|only|somente|apenas)\s+)*"
    r"(?:typo\w*|ortograf\w*|spelling)|"
    r"renome\w*|rename|tradu\w*|translate|formate|formatar|format|resuma|resumir|summari\w*|"
    r"explique (?:este|esse|o) comando|explain (?:this|the) command)\b")
OTHER_ACTION = re.compile(
    r"\b(?:implement\w*|desenvolv\w*|build|crie|criar|create|adicion\w*|add|"
    r"corrij\w*|fix|repair|resolv\w*|solve|investig\w*|diagnos\w*|projete|design|"
    r"refator\w*|refactor\w*|redesign|reestrutur\w*|optimiz\w*|otimiz\w*|"
    r"elimin\w*|remov\w*|delet\w*|exclu\w*|apagu\w*|alter\w*|chang\w*|"
    r"execut\w*|run|deploy\w*|encrypt\w*|criptograf\w*)\b")
NAMED_IDENTIFIER = re.compile(
    r"\b(variavel|variable|parametro|parameter|argumento|argument|constante|constant)\s+\w+\b")
OUTPUT_FORMAT = re.compile(
    r"^(?:retorne|responda|devolva|return|respond|reply|output)\s+"
    r"(?:(?:somente|apenas|only|just|with|com)\s+)*(?:(?:o|the|a|an)\s+)?(?:objeto\s+)?json\b")
NO_OTHER_WORK = re.compile(r"^(?:sem|no|without)\s+(?:markdown|(?:outras?|other)\s+(?:alterac(?:ao|oes)|changes?))$")


def requested_work(text: str) -> tuple[str, bool]:
    """Conservative clause heuristic, not a parser or semantic risk assessment."""
    work = PATHS.sub(" reference ", QUOTED.sub(" literal ", text))
    clauses = [NEGATIVE.sub("", clause).strip() for clause in CLAUSES.split(work)]
    clauses = [clause for clause in clauses if clause]
    actions = []
    for clause in clauses:
        presentation = OUTPUT_FORMAT.match(clause)
        if NO_OTHER_WORK.fullmatch(clause) or (presentation and not OTHER_ACTION.search(clause[presentation.end():])):
            continue
        actions.append(clause)
    simple = bool(actions)
    for clause in actions:
        match = SIMPLE_ACTION.match(clause)
        if not match or OTHER_ACTION.search(clause[match.end():]):
            simple = False
    # A named identifier is a reference, but a simple action must never hide
    # risk words in the rest of the requested work.
    risk_text = [NAMED_IDENTIFIER.sub(r"\1 identifier", clause)
                 if SIMPLE_ACTION.match(clause) else clause for clause in clauses]
    return " ; ".join(risk_text), simple


@dataclass(frozen=True)
class Decision:
    tier: str
    model: str
    score: int
    reasons: tuple[str, ...]
    scanned_chars: int
    total_chars: int
    policy: str = "local-rules-v4"

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
    work, simple = requested_work(text)
    words = len(text.split())
    reasons = []
    score = 0
    for reason, weight, pattern in RULES:
        if pattern.search(work):
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
    if score >= 5:
        tier = "advanced"
    elif score == 0 and simple and words <= 100 and paths <= 2 and not truncated:
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
