"""Local, conservative task boundaries. No prompt storage or model calls."""

from datetime import datetime, timezone
import re

from .classifier import normalize

NEW = re.compile(r"^(?:nova tarefa|novo assunto|outra tarefa|new task|new topic)\b")
CONTINUE = re.compile(
    r"^(?:continue\b|continuar\b|retome\b|retomar\b|continuando\b|"
    r"na mesma tarefa\b|same task\b|carry on\b|resume\b|"
    r"(?:agora|now)\s+(?:teste|test|valide|validate|verifique|check)\s+(?:isso|isto|o resultado|it|that|the result)\b|"
    r"(?:e|and)\s+(?:tambem\s+|also\s+)?(?:corrija|fix|adicione|add|teste|test|valide|validate)\b)")
MAX_IDLE_SECONDS = 12 * 60 * 60


def choose(prompt, latest, mode="auto", instant=None):
    if mode == "new":
        return "new", "explicit_new"
    if mode == "continue":
        if latest is None:
            raise ValueError("Não há tarefa neste projeto. Use ctr new com a tarefa inicial.")
        return "resume", "explicit_continue"
    if latest is None:
        if prompt and CONTINUE.match(normalize(prompt.strip())):
            raise ValueError("Não há tarefa neste projeto para continuar. Use ctr new com a tarefa inicial.")
        return "new", "no_project_task"
    if prompt is None:
        return "resume", "open_latest"
    text = normalize(prompt.strip())
    if NEW.match(text):
        return "new", "new_task_marker"
    if CONTINUE.match(text):
        # Old or failed work needs an explicit choice; silently opening a new
        # task for 'continue' would lose the user's intended context.
        at = latest.get("last_launched_at") or latest["created_at"]
        age = ((instant or datetime.now(timezone.utc)) - datetime.fromisoformat(at)).total_seconds()
        if not 0 <= age <= MAX_IDLE_SECONDS:
            raise ValueError("A última tarefa não é recente. Use ctr resume UUID ou ctr run --continue.")
        if latest.get("last_exit_code") not in (None, 0):
            raise ValueError("A última execução falhou. Confira ctr show; use ctr resume UUID ou ctr recover.")
        return "resume", "continuation_marker"
    return "new", "no_clear_continuation"
