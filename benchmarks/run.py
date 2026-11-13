"""Reproducible local latency and policy examples, not a quality/cost claim."""

import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claude_task_router.classifier import classify  # noqa: E402


def main():
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    failures = []
    elapsed = []
    for _ in range(100):
        for case in cases:
            start = time.perf_counter_ns()
            decision = classify(case["prompt"])
            elapsed.append((time.perf_counter_ns() - start) / 1e6)
            if decision.tier != case["tier"] and case not in failures:
                failures.append(case)
    startup = []
    for _ in range(5):
        start = time.perf_counter_ns()
        subprocess.run([sys.executable, "-m", "claude_task_router", "classify", "Fix typo"],
                       cwd=ROOT, check=True, capture_output=True)
        startup.append((time.perf_counter_ns() - start) / 1e6)
    print(json.dumps(dict(
        python=platform.python_version(), platform=platform.system(),
        examples=len(cases), mismatches=failures, samples=len(elapsed),
        classifier_p50_ms=round(statistics.median(elapsed), 4),
        classifier_p95_ms=round(sorted(elapsed)[int(len(elapsed) * .95)], 4),
        cli_startup_p50_ms=round(statistics.median(startup), 2),
        router_inference_calls=0, router_injected_context_tokens=0,
        note="Exemplos sintéticos da política; não medem qualidade real ou economia de faturamento."
    ), ensure_ascii=False, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
