#!/usr/bin/env python3
"""Score the frozen conversation corpus locally, without starting Claude."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_task_router.conversation import detect
from claude_task_router.topics import TaskContext


def evaluate(corpus_path):
    raw = corpus_path.read_bytes()
    corpus = json.loads(raw)
    labels = corpus["labels"]
    development_prompts = {row["prompt"] for row in corpus["development"]}
    results = {}
    for split in ("development", "evaluation"):
        matrix = {a: {b: 0 for b in labels} for a in labels}
        errors = []
        durations = []
        languages = {}
        excluded = []
        for case in corpus[split]:
            if split == "evaluation" and case["prompt"] in development_prompts:
                excluded.append(case["id"])
                continue
            started = time.perf_counter_ns()
            observed = detect(case["prompt"], TaskContext.from_prompt(case["previous_task"]))
            durations.append((time.perf_counter_ns() - started) / 1_000_000)
            expected = case["expected"]
            matrix[expected][observed] += 1
            language = languages.setdefault(case["language"],
                {a: {b: 0 for b in labels} for a in labels})
            language[expected][observed] += 1
            if observed != expected:
                errors.append(dict(id=case["id"], expected=expected, observed=observed))
        tp = matrix["new"]["new"]
        fp = matrix["continue"]["new"] + matrix["ambiguous"]["new"]
        fn = sum(matrix["new"].values()) - tp
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        ambiguity_ok = matrix["ambiguous"]["ambiguous"] == sum(matrix["ambiguous"].values())
        continuation_ok = matrix["continue"]["new"] == 0
        results[split] = dict(matrix=matrix, by_language=languages, errors=errors,
            scored_cases=len(durations), excluded_development_overlap_ids=excluded,
            true_positives=tp, false_positives=fp, false_negatives=fn,
            precision=precision, recall=recall,
            ambiguity_abstention_passed=ambiguity_ok,
            continuation_preservation_passed=continuation_ok,
            latency_ms=dict(p50=statistics.median(durations),
                p95=sorted(durations)[math.ceil(len(durations) * .95) - 1]),
            boundary_thresholds_passed=(ambiguity_ok and continuation_ok and fp == 0 and precision is not None
                                       and precision >= .98 and recall is not None and recall >= .9))
    source_root = Path(__file__).resolve().parent.parent / "claude_task_router"
    return dict(scope="offline_contextual_detector_only", corpus_sha256=hashlib.sha256(raw).hexdigest(),
        detector_sha256={name: hashlib.sha256((source_root/name).read_bytes()).hexdigest()
                         for name in ("conversation.py", "topics.py")},
        inferred_boundaries_require_live_choice=True,
        feature_acceptance=False, native_e2e="separate evidence required",
        inference_calls=0, results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).with_name("conversation-boundaries-v2.json"))
    args = parser.parse_args()
    result = evaluate(args.corpus)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0 if result["results"]["evaluation"]["boundary_thresholds_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
