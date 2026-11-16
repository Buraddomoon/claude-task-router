"""Metadata-only accounting for session-cumulative native result counters."""

import hashlib
import math
from pathlib import Path
import re
import subprocess

TOKEN_FIELDS = dict(input_tokens="inputTokens", cache_creation_input_tokens="cacheCreationInputTokens",
                    cache_read_input_tokens="cacheReadInputTokens", output_tokens="outputTokens")


def number(value, integer=False):
    valid = type(value) is int if integer else type(value) in (int, float)
    try:
        return value if valid and math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def provenance(binary):
    """No paths, command output, environment or credentials in exported evidence."""
    try:
        path = Path(binary).resolve(strict=True)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
        version = re.fullmatch(r"(\d+\.\d+\.\d+) \(Claude Code\)\s*", result.stdout)
        return dict(version=version[1] if version and result.returncode == 0 else None,
                    binary_sha256=digest.hexdigest())
    except (OSError, subprocess.SubprocessError):
        return dict(version=None, binary_sha256=None)


def stable(before, after):
    return bool(before and before.get("version") and before.get("binary_sha256") and before == after)


def snapshot(payload):
    payload = payload if isinstance(payload, dict) else {}
    raw = payload.get("modelUsage")
    models = {}
    if isinstance(raw, dict):
        for model, counters in raw.items():
            # Model identifiers are metadata, but untrusted output must not be
            # allowed to smuggle free text or credentials into public records.
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\[\]-]{0,511}", model) or model.lower().startswith("sk-"):
                continue
            counters = counters if isinstance(counters, dict) else {}
            models[model] = {key: number(counters.get(native), integer=True)
                             for key, native in TOKEN_FIELDS.items()}
    session = payload.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[a-f0-9-]{36}", session):
        session = None
    return dict(session_id=session, cost_usd=number(payload.get("total_cost_usd")), models=models)


def marginal(current, previous=None, resumed=False):
    """Subtract the last complete result from the SAME session, model by model.

    Never interpret a lost baseline, reset, disappearing model or counter
    decrease as a free call. Preserve current cumulative counters separately.
    `usage` is intentionally unused: it omits subagent activity and can have
    different scope from modelUsage/total_cost_usd.
    """
    issues = []
    if not current["session_id"]:
        issues.append("missing_session_id")
    if resumed and (not previous or not previous["session_id"] or
                    current["session_id"] != previous["session_id"]):
        issues.append("missing_or_changed_resume_baseline")
    before = previous if resumed and previous else dict(cost_usd=0, models={})
    cost = None
    if current["cost_usd"] is not None and before["cost_usd"] is not None:
        delta = current["cost_usd"] - before["cost_usd"]
        if delta >= -1e-10:
            cost = max(0, delta)
        else:
            issues.append("cost_counter_decreased")
    else:
        issues.append("missing_cost")
    models = {}
    if not current["models"]:
        issues.append("missing_model_usage")
    if set(before["models"]) - set(current["models"]):
        issues.append("model_counter_disappeared")
    for model, counters in current["models"].items():
        old = before["models"].get(model, dict.fromkeys(TOKEN_FIELDS, 0))
        delta = {}
        for key, value in counters.items():
            prior = old[key]
            delta[key] = value - prior if value is not None and prior is not None and value >= prior else None
        if any(v is None for v in delta.values()):
            issues.append("missing_or_decreased_token_counter")
        models[model] = delta
    if "missing_or_changed_resume_baseline" in issues:
        cost = None
        models = {m: dict.fromkeys(TOKEN_FIELDS) for m in models}
    tokens = {key: sum(values[key] for values in models.values())
              if models and all(values[key] is not None for values in models.values())
              and not set(before["models"]) - set(current["models"]) else None for key in TOKEN_FIELDS}
    return dict(cli_estimated_cost_usd=cost, token_usage=tokens,
                total_tokens=sum(tokens.values()) if all(v is not None for v in tokens.values()) else None,
                effective_models=[model for model, values in models.items()
                                  if any(value is not None and value > 0 for value in values.values())],
                cumulative=current, measurement_issues=sorted(set(issues)),
                api_invoice_usd=None, subscription_quota=None,
                billing_source="unverified", quota_source="unverified")
