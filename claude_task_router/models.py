"""Use only public native CLI commands; never read credential stores."""

import json
import subprocess
import time

from .config import validate_model
from .launcher import executable


def inspect_model(binary, model=None, probe=False):
    if model is not None:
        validate_model(model)
    if probe and model is None:
        raise ValueError("--probe exige um modelo explícito.")
    command = [executable(binary), "--print", "--output-format", "json", "--tools", "",
               "--no-chrome", "--restricted", "--no-session-persistence", "--max-turns", "1",
               "--max-budget-usd", "0.03" if probe else "0.01"]
    if probe:
        command += ["--model", model]
    command += ["--", "Respond with exactly OK." if probe else "/model" + (" " + model if model else "")]
    start = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError()
    except ValueError:
        return dict(ok=False, status="invalid_cli_response", requested=model, probe=probe), 1
    text = payload.get("result", "")
    turns, cost = payload.get("num_turns"), payload.get("total_cost_usd")
    if probe:
        observed = list(payload.get("modelUsage", {}))
        from .state import matches_choice
        ok = (result.returncode == 0 and not payload.get("is_error")
              and isinstance(text, str) and text.strip() == "OK"
              and len(observed) == 1 and matches_choice(model, observed[0]))
        return dict(ok=ok, status="probe_passed" if ok else "probe_failed", requested=model,
                    effective_models=observed, native_turns=turns, cli_estimated_cost_usd=cost,
                    duration_seconds=round(time.monotonic() - start, 3), probe=True,
                    note="Teste real curto; custo é estimativa do CLI, não faturamento. Acesso pode mudar."), 0 if ok else 1
    # A native slash-command error can have exit code 0 and is_error=false.
    # Only known local responses with zero turns/cost are accepted as evidence.
    local = (result.returncode == 0 and not payload.get("is_error") and turns == 0
             and cost == 0 and isinstance(text, str))
    accepted = local and (text.startswith("Set model to ") if model else text.startswith("Current model:"))
    rejected = local and ("not found" in text or "restricted" in text.lower() or "not available" in text.lower())
    return dict(ok=accepted, status="accepted_by_cli" if accepted else "rejected_by_cli" if rejected else "unconfirmed",
                requested=model, native_turns=turns, cli_estimated_cost_usd=cost, probe=False,
                native_message=text[:2000] if local else None,
                note="Validação nativa sem inferência observada; aliases não comprovam autorização de todos os IDs. "
                     "Use --probe MODELO para um teste real explícito com consumo."), 0 if accepted else 1
