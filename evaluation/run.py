"""Evaluate fixed labels and bounded latency. No inference or account needed."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claude_task_router.classifier import classify  # noqa: E402

TIERS = ("economy", "balanced", "advanced")


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))]


def evaluate(split):
    raw = Path(__file__).with_name("corpus.json").read_bytes()
    cases = [case for case in json.loads(raw) if case["split"] == split]
    confusion = {expected: {actual: 0 for actual in TIERS} for expected in TIERS}
    categories = {}
    errors = []
    under = over = correct = 0
    latencies = []
    for case in cases:
        decision = classify(case["prompt"])
        expected, actual = case["tier"], decision.tier
        confusion[expected][actual] += 1
        delta = TIERS.index(actual) - TIERS.index(expected)
        under += delta < 0
        over += delta > 0
        correct += delta == 0
        group = categories.setdefault(case["category"], dict(total=0, correct=0))
        group["total"] += 1
        group["correct"] += delta == 0
        if delta:
            errors.append(dict(id=case["id"], prompt=case["prompt"], expected=expected,
                               actual=actual, rationale=case["rationale"], reasons=decision.reasons))
        for _ in range(100):
            start = time.perf_counter_ns()
            classify(case["prompt"])
            latencies.append((time.perf_counter_ns() - start) / 1e6)
    maximum = ("Investigue a causa raiz. " + "dados " * 50000)[:256 * 1024]
    boundary_times = []
    for _ in range(20):
        start = time.perf_counter_ns()
        boundary = classify(maximum)
        boundary_times.append((time.perf_counter_ns() - start) / 1e6)
    count = len(cases)
    accuracy, under_rate, over_rate = correct / count, under / count, over / count
    checks = dict(accuracy=accuracy >= .85, undersizing=under_rate <= .10,
                  oversizing=over_rate <= .15, advanced_never_economy=confusion["advanced"]["economy"] == 0,
                  typical_latency=percentile(latencies, .95) <= 2,
                  maximum_latency=percentile(boundary_times, .95) <= 150)
    return dict(split=split, corpus_sha256=hashlib.sha256(raw).hexdigest(),
                policy=classify("help").policy, python=platform.python_version(), platform=platform.system(),
                cases=count, exact=correct, undersized=under, oversized=over,
                accuracy=round(accuracy, 4), undersizing_rate=round(under_rate, 4),
                oversizing_rate=round(over_rate, 4), confusion=confusion, categories=categories,
                mismatches=errors, classifier_p50_ms=round(statistics.median(latencies), 4),
                classifier_p95_ms=round(percentile(latencies, .95), 4),
                maximum_input_bytes=len(maximum.encode()), maximum_scanned_chars=boundary.scanned_chars,
                maximum_p95_ms=round(percentile(boundary_times, .95), 4),
                checks=checks, passed=all(checks.values()), router_inference_calls=0,
                router_injected_context_tokens=0,
                limitation="Synthetic tier labels; not real answer quality, billing or token savings.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "evaluation"), default="evaluation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.split)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
