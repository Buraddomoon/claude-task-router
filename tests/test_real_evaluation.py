import json
from pathlib import Path
import unittest
from unittest.mock import patch

from evaluation.real import execute, quality, summarize
from evaluation.efficiency_audit import analyze, audit


class RealEvaluationTests(unittest.TestCase):
    def test_historical_token_increase_is_cache_not_price_or_output(self):
        report = audit()
        v4 = report["datasets"][1]
        self.assertEqual(v4["routed_minus_baseline_tokens"], dict(
            input_tokens=0, output_tokens=0, cache_creation_input_tokens=-627, cache_read_input_tokens=5715))
        self.assertEqual(sum(v4["routed_minus_baseline_tokens"].values()), 5088)
        self.assertAlmostEqual(report["known_historical_cost_usd"], .07725063)
        self.assertEqual(report["datasets"][2]["arms"]["baseline"]["calls"], 9)
        self.assertFalse(report["general_savings_proven"])
        self.assertFalse(report["policy_changed"])
        self.assertIsNone(v4["native_router_overhead_seconds"])

    def test_historical_unknown_spend_is_not_reported_as_zero(self):
        rows = [dict(arm="routed", execution_ok=False, quality_passed=False,
                     cli_estimated_cost_usd=None, duration_seconds=2, total_tokens=None)]
        result = analyze(rows)["arms"]["routed"]
        self.assertIsNone(result["cost_usd"]["total"])
        self.assertFalse(result["cost_usd"]["complete"])
        self.assertEqual(result["execution_failures"], 1)

    def test_spawn_failure_is_a_recordable_failure_without_retry(self):
        with patch("evaluation.real.subprocess.Popen", side_effect=FileNotFoundError()) as spawn:
            self.assertEqual(execute(["missing"], Path.cwd(), {}), (2, ""))
            self.assertEqual(spawn.call_count, 1)

    def test_pure_arithmetic_grader_rejects_executable_or_incorrect_code(self):
        case = dict(kind="python")
        self.assertTrue(quality(case, json.dumps(dict(code="def pages(total, size):\n return (total + size - 1) // size"))))
        for code in ("import os\ndef pages(total,size): return 1",
                     "def pages(total,size): return __import__('os').system('echo bad')",
                     "def pages(total,size):\n while True: pass",
                     "@print\ndef pages(total,size): return 0",
                     "def pages(total,size=open('secret')): return 0",
                     "def pages(total,size): return total ** (10 ** 10)",
                     "def pages(total,size): return total//size+1",
                     "def pages(total,size): return total.__class__",
                     "def pages(total,size): return total/size"):
            self.assertFalse(quality(case, json.dumps(dict(code=code))), code)

    def test_objective_case_verifiers_and_failures_are_counted(self):
        cases = json.loads((Path(__file__).resolve().parent.parent / "evaluation/real-cases.json").read_text())
        self.assertTrue(quality(cases[0], '{"text":"The quick brown fox."}'))
        self.assertFalse(quality(cases[0], '{"text":"Teh quick brown fox."}'))
        self.assertFalse(quality(cases[2], '{"b":[2,1],"a":1}'))
        failed = dict(arm="routed", quality_passed=False, execution_ok=False,
                      cli_estimated_cost_usd=.02, duration_seconds=1, total_tokens=100)
        summary = summarize([failed], 2)
        self.assertEqual(summary["totals"]["routed"]["cost_usd"], .02)
        self.assertFalse(summary["complete"])
        self.assertTrue(all(value is None for value in summary["observed_reduction_percent"].values()))
