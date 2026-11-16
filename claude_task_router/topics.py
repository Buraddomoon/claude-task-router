"""Limited lexical task context, kept only in memory. No model or embeddings."""

from dataclasses import dataclass
import json
import re

from .boundary import CONTINUE
from .classifier import normalize, QUOTED

SCAN_CHARS = 65536
STOP = set("""a an o os as the um uma uns umas de da das do dos e and em no nos na nas
of on in for to por para com with from at ao aos pela pelo seu sua seus suas my our
your this that these those este esse esta essa estes essas isto isso it its eu i
we voce voces nosso nossa meu minha me um novo nova new outro outra another old
agora now por favor please preciso need want quero tarefa task trabalho work
only just somente apenas also tambem mais more one uma script code codigo
system sistema service servico part parte result resultado current atual
""".split())
ACTION = r"(?:implement\w*|desenvolv\w*|develop|build|crie|criar|create|projete|design|planeje|plan|prepare|monte|investig\w*|migr\w*|refator\w*|refactor|corrij\w*|fix|adjust|ajust\w*|write|escrev\w*|deploy|configure|configur\w*)"
HEAD = re.compile(r"^(?:(?:please|por favor)\s+)?(?:(?:i (?:need|want) to|preciso(?: de)?|quero)\s+)?" + ACTION + r"\b")
ACTION_WORD = re.compile(r"^(?:" + ACTION + r"|corrigir|rename|renome\w*|tradu\w*|translat\w*|format\w*|valid\w*|test\w*|documente|documentar|document|documenting|revis\w*|review|retome|continue|continuar)$")
PRESENTATION = re.compile(r"(?:^|[.;]\s*)(?:responda|respond|reply|retorne|return|output)\b.*$", re.S)
COMPLETED = re.compile(r"^.{0,160}\b(?:terminamos|terminado|terminada|concluido|concluida|pronto|pronta|finished|done|complete|completed)\b[^.;!?]*[.;]\s*", re.S)
PARKED = re.compile(r"^(?:deixe|keep|park|pause)\b.{1,180}\b(?:depois|later)\b[^.;!?]*[.;]\s*", re.S)
UNCERTAIN = re.compile(r"\b(?:talvez|maybe|perhaps|possivelmente|eventualmente|depois|later)\b")
VAGUE = re.compile(r"\b(?:aquela parte|essa parte|a parte|the part|that part|that system|aquele sistema|outra coisa|something else)\b")
DENIED_BOUNDARY = re.compile(r"(?:^nova tarefa\s+nao\b|^new task\s*,?\s*no\b|\b(?:nao (?:e|eh|comece|abra|inicie)|do not (?:start|begin)|don't (?:start|begin)|not)\b.{0,32}\b(?:nova tarefa|outra tarefa|new task|another task)\b)")
SUPPORT = re.compile(r"^(?:adicione|add|atualize|update|teste|test|valide|validate|verifique|check|traduza|translate)\b")


def terms(text):
    text = PRESENTATION.sub("", QUOTED.sub(" ", normalize(text[:SCAN_CHARS])))
    result = set()
    for word in re.findall(r"[a-z][a-z0-9_]{2,}", text):
        if word in STOP or ACTION_WORD.fullmatch(word):
            continue
        if word.startswith(("autentic", "authentic")) or word in {"oauth", "login", "jwt"}:
            word = "authentication"
        elif word.startswith(("parser", "parsing", "analisador")):
            word = "parser"
        elif word.startswith(("document", "manual", "readme")):
            word = "documentation"
        elif word.endswith("s") and len(word) > 4:
            word = word[:-1]
        result.add(word)
        if len(result) >= 128:
            break
    return frozenset(result)


@dataclass(frozen=True)
class TaskContext:
    vocabulary: frozenset[str]

    @classmethod
    def from_prompt(cls, prompt):
        return cls(terms(prompt or ""))

    @classmethod
    def from_transcript(cls, store, task):
        """Read one original user goal from an already owned native transcript.

        Never copy it to SQLite, logs or another session. Missing, oversized or
        untrusted history means no context and therefore conservative abstention.
        """
        try:
            path = store.valid_transcript(task.get("transcript_path"), task["id"])
            if path is None:
                return cls(frozenset())
            with path.open("rb") as stream:
                raw = stream.read(1024 * 1024)
            for line in raw.splitlines():
                row = json.loads(line)
                if (not isinstance(row, dict) or row.get("type") != "user"
                        or row.get("sessionId") != task["id"] or row.get("isMeta")):
                    continue
                content = row.get("message", {}).get("content")
                if isinstance(content, list):
                    content = "\n".join(b["text"] for b in content
                        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
                if isinstance(content, str) and content.strip():
                    return cls.from_prompt(content)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return cls(frozenset())


def contextual_action(prompt, context):
    text = normalize(prompt[:SCAN_CHARS].strip())
    if DENIED_BOUNDARY.search(text):
        return "continue"
    # A future/compound intention is not a boundary to apply now.
    candidate = PARKED.sub("", COMPLETED.sub("", PRESENTATION.sub("", text).strip()))
    if UNCERTAIN.search(candidate):
        return "ambiguous"
    if CONTINUE.match(text):
        return "continue"
    if SUPPORT.match(text):
        return "continue"
    target = terms(candidate)
    if context and target & context.vocabulary:
        return "continue"
    if VAGUE.search(candidate) or not HEAD.match(candidate):
        return "ambiguous"
    if not context or not context.vocabulary or not target:
        return "ambiguous"
    if target & context.vocabulary:
        return "continue"
    return "new"
