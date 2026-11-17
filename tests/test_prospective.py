import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evaluation.measurements import marginal, provenance, snapshot, stable
from evaluation.prospective import CohortStopped, PROTOCOL, call, digest, freeze, main, run, summarize
from evaluation.real import ROOT, execute
from evaluation.smoke import main as smoke_main

SESSION = "12345678-1234-4234-8234-123456789abc"
CLIENT = dict(version="2.1.325", binary_sha256="a" * 64)


def payload(cost=.02, input_tokens=10, output=5, cache_write=20, cache_read=100):
    return dict(session_id=SESSION, total_cost_usd=cost, subtype="success", result="OK",
                modelUsage={"claude-sonnet-5-5": dict(inputTokens=input_tokens, outputTokens=output,
                    cacheCreationInputTokens=cache_write, cacheReadInputTokens=cache_read)})


def cohort():
    rows = []
    for arm in ("baseline", "routed"):
        for turn in (1, 2):
            rows.append(dict(case="T01", repetition=1, arm=arm, turn=turn, requested_model="sonnet",
                             effective_models=["claude-sonnet-5-5"], model_confirmed=True,
                             client_before=CLIENT, client_after=CLIENT, measurement_issues=[],
                             execution_ok=True, functional_passed=True,
                             cli_estimated_cost_usd=.02 if arm == "baseline" else .01,
                             total_tokens=100 if arm == "baseline" else 80,
                             duration_seconds=2 if arm == "baseline" else 1))
    return dict(records=rows, planned_calls=4, lock=dict(tasks=[dict(id="T01")]))


def private_manifest(root):
    projects = []
    for index in range(2):
        project = root / f"private-project-{index}"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        (project / "example.txt").write_text("private code")
        subprocess.run(["git", "-C", str(project), "add", "."], check=True)
        subprocess.run(["git", "-C", str(project), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                        "commit", "-qm", "snapshot"], check=True)
        commit = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
        projects.append((project, commit))
    tasks = []
    for index, category in enumerate(("fix", "feature", "refactor", "investigation") * 2):
        prompts = []
        for turn in (1, 2):
            path = root / f"private-{index}-{turn}.txt"
            path.write_bytes(f"private request {index} / {turn}\r\n".encode())
            prompts.append(str(path))
        project, commit = projects[index % 2]
        tasks.append(dict(id=f"T{index+1:02}", category=category, project=str(project), commit=commit,
                          prompts=prompts, acceptance=[[sys.executable, "-c", "pass"]] * 2))
    manifest = root / "private.json"
    manifest.write_text(json.dumps(dict(authorized=True, not_used_for_calibration=True, tasks=tasks)))
    return manifest, tasks


class MeasurementTests(unittest.TestCase):
    def test_unverified_client_prevents_first_inference_without_fabricating_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            report = dict(records=[])
            with patch("evaluation.prospective.provenance", return_value=dict(version=None, binary_sha256=None)), \
                    patch("evaluation.prospective.execute") as execute, self.assertRaises(CohortStopped):
                call(report, output, [], ROOT, {}, "binary", case="T01", arm="baseline",
                     repetition=1, turn=1, choice="sonnet")
            execute.assert_not_called()
            saved = json.loads(output.read_bytes())
            self.assertEqual(saved["records"], [])
            self.assertEqual(saved["stopped"], "client_changed_or_unverified")

    def test_environment_drift_stops_before_next_inference_and_preserves_spend(self):
        changed_client = dict(version="2.1.326", binary_sha256="b" * 64)
        for client, source, reason in (
            (changed_client, "a" * 64, "client_changed_or_unverified"),
            (CLIENT, "b" * 64, "router_or_harness_sources_changed"),
        ):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                report = dict(records=[])
                with patch("evaluation.prospective.provenance", return_value=CLIENT), \
                        patch("evaluation.prospective.sources_hash", return_value="a" * 64), \
                        patch("evaluation.prospective.execute", return_value=(0, json.dumps(payload()))) as execute:
                    previous, _ = call(report, output, [], ROOT, {}, "binary", case="T01", arm="baseline",
                                       repetition=1, turn=1, choice="sonnet")
                    self.assertEqual(execute.call_count, 1)
                first = copy.deepcopy(report["records"])
                with patch("evaluation.prospective.provenance", return_value=client), \
                        patch("evaluation.prospective.sources_hash", return_value=source), \
                        patch("evaluation.prospective.execute") as execute, self.assertRaises(CohortStopped):
                    call(report, output, [], ROOT, {}, "binary", case="T01", arm="baseline",
                         repetition=1, turn=2, choice="sonnet", previous=previous)
                execute.assert_not_called()
                saved = json.loads(output.read_bytes())
                self.assertEqual(saved["records"], first)
                self.assertEqual(saved["stopped"], reason)
                self.assertEqual(saved["records"][0]["cli_estimated_cost_usd"], .02)

    def test_alias_drift_preserves_the_call_cost_and_invalidates_measurement(self):
        changed = payload()
        changed["modelUsage"] = {"claude-sonnet-5-6": changed["modelUsage"].pop("claude-sonnet-5-5")}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            report = dict(records=[])
            with patch("evaluation.prospective.provenance", return_value=CLIENT), \
                    patch("evaluation.prospective.execute", side_effect=[(0, json.dumps(p)) for p in (payload(), changed)]):
                for case in ("T01", "T02"):
                    call(report, output, [], ROOT, {}, "binary", case=case, arm="baseline",
                         repetition=1, turn=1, choice="sonnet")
            saved = json.loads(output.read_bytes())
            self.assertEqual(len(saved["records"]), 2)
            self.assertEqual(sum(r["cli_estimated_cost_usd"] for r in saved["records"]), .04)
            self.assertIn("effective_model_changed_within_cohort", saved["records"][-1]["measurement_issues"])

    def test_resume_subtracts_history_per_model_and_preserves_cache(self):
        initial = snapshot(payload())
        current = snapshot(payload(cost=.027, input_tokens=13, output=8, cache_write=24, cache_read=200))
        result = marginal(current, initial, resumed=True)
        self.assertAlmostEqual(result["cli_estimated_cost_usd"], .007)
        self.assertEqual(result["token_usage"], dict(input_tokens=3, output_tokens=3,
                                                   cache_creation_input_tokens=4, cache_read_input_tokens=100))
        self.assertEqual(result["total_tokens"], 110)
        self.assertEqual(result["cumulative"]["cost_usd"], .027)
        self.assertEqual(result["measurement_issues"], [])
        self.assertIsNone(result["api_invoice_usd"])
        self.assertIsNone(result["subscription_quota"])

    def test_resume_uses_active_delta_model_not_inactive_history(self):
        before = snapshot(payload())
        after = copy.deepcopy(before)
        after["cost_usd"] += .01
        after["models"]["claude-haiku-5-5"] = dict(input_tokens=1, output_tokens=2,
                                                  cache_creation_input_tokens=3, cache_read_input_tokens=4)
        result = marginal(after, before, resumed=True)
        self.assertEqual(result["effective_models"], ["claude-haiku-5-5"])
        self.assertEqual(result["total_tokens"], 10)

    def test_missing_reset_or_decreased_resume_is_not_free_or_comparable(self):
        before = snapshot(payload())
        for after, previous in ((snapshot(payload(cost=.01, input_tokens=1)), before),
                                (snapshot(payload()), None),
                                ({**before, "session_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}, before)):
            result = marginal(after, previous, resumed=True)
            self.assertTrue(result["measurement_issues"])
            self.assertIsNone(result["cli_estimated_cost_usd"])
        broken = copy.deepcopy(before)
        broken["models"] = {}
        result = marginal(broken, before, resumed=True)
        self.assertIn("model_counter_disappeared", result["measurement_issues"])
        self.assertIsNone(result["total_tokens"])

    def test_incomplete_or_invalid_counters_stay_missing(self):
        for value in (None, float("nan"), float("inf"), -1, True, "0"):
            result = marginal(snapshot({**payload(), "total_cost_usd": value}))
            self.assertIsNone(result["cli_estimated_cost_usd"])
        malformed = payload()
        malformed["usage"] = dict(input_tokens=1, output_tokens=1)
        malformed["modelUsage"] = None
        self.assertIsNone(marginal(snapshot(malformed))["total_tokens"])
        malformed["modelUsage"] = {"sk-secret": {}, "private prompt text": {}}
        self.assertEqual(snapshot(malformed)["models"], {})

    def test_provenance_does_not_export_paths_or_untrusted_version_output(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "private-name"
            binary.write_bytes(b"binary")
            with patch("evaluation.measurements.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "2.1.325 (Claude Code)\n")):
                observed = provenance(str(binary))
            self.assertTrue(stable(observed, observed))
            self.assertNotIn(directory, json.dumps(observed))
            self.assertFalse(stable(observed, {**observed, "version": "2.1.326"}))
            with patch("evaluation.measurements.subprocess.run", side_effect=subprocess.TimeoutExpired([], 15)):
                self.assertFalse(stable(provenance(str(binary)), observed))

    def test_timeout_records_failure_and_kills_child_without_retry(self):
        code, text = execute([sys.executable, "-c", "import time; time.sleep(30)"], ROOT, os.environ, timeout=.03)
        self.assertEqual((code, text), (124, ""))

    def test_attempt_is_saved_before_spawn_and_missing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            report = dict(records=[])

            def failed_spawn(*args, **kwargs):
                saved = json.loads(output.read_bytes())
                self.assertEqual(saved["records"][0]["status"], "started")
                return 2, "private unparseable output"

            with patch("evaluation.prospective.provenance", return_value=CLIENT), \
                    patch("evaluation.prospective.execute", side_effect=failed_spawn) as attempted:
                call(report, output, [], ROOT, {}, "binary", case="T01", arm="routed",
                     repetition=1, turn=1, choice="sonnet")
            row = report["records"][0]
            self.assertEqual(attempted.call_count, 1)
            self.assertFalse(row["execution_ok"])
            self.assertIsNone(row["cli_estimated_cost_usd"])
            self.assertNotIn("private", output.read_text())

    def test_interrupted_attempt_remains_saved_with_unknown_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            report = dict(records=[])
            with patch("evaluation.prospective.provenance", return_value=CLIENT), \
                    patch("evaluation.prospective.execute", side_effect=KeyboardInterrupt), \
                    self.assertRaises(KeyboardInterrupt):
                call(report, output, [], ROOT, {}, "binary", case="T01", arm="baseline",
                     repetition=1, turn=1, choice="sonnet")
            row = json.loads(output.read_bytes())["records"][0]
            self.assertEqual(row["status"], "interrupted")
            self.assertIsNone(row["cli_estimated_cost_usd"])


class ProspectiveTests(unittest.TestCase):
    def test_runner_stops_at_client_drift_and_retains_completed_acceptance_and_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = private_manifest(root)
            protocol = json.loads(PROTOCOL.read_bytes())
            lock = freeze(manifest, protocol)
            output = root / "report.json"
            changed_client = dict(version="2.1.326", binary_sha256="b" * 64)
            with patch("evaluation.prospective.uuid.uuid4", return_value=SESSION), \
                    patch("evaluation.prospective.provenance", side_effect=[CLIENT, CLIENT, changed_client]), \
                    patch("evaluation.prospective.execute", side_effect=[(0, json.dumps(payload())), (0, "")]) as execute:
                report = run(manifest, lock, protocol, "binary", output, root / "runs")
            self.assertEqual(execute.call_count, 2)  # One inference, then its functional check.
            self.assertEqual(report["stopped"], "client_changed_or_unverified")
            self.assertEqual(len(report["records"]), 1)
            self.assertTrue(report["records"][0]["functional_passed"])
            self.assertEqual(report["summary"]["totals"]["baseline"]["known_cost_usd"], .02)
            self.assertEqual(report["summary"]["verdict"], "inconclusive")
            self.assertEqual(json.loads(output.read_bytes()), report)

    def test_observed_router_new_resume_and_marginal_accounting_without_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "fake-native"
            # Delegate lifecycle/hooks to the existing contract double, then
            # add realistic cumulative counters. This never invokes Claude.
            binary.write_text("#!/usr/bin/env python3\n" +
                "import json, subprocess, sys\n" +
                "if sys.argv[1:] == ['--version']:\n print('2.1.325 (Claude Code)'); raise SystemExit(0)\n" +
                f"r = subprocess.run([sys.executable, {str(ROOT / 'tests/fake_claude.py')!r}, *sys.argv[1:]], capture_output=True, text=True)\n" +
                "if r.returncode: raise SystemExit(r.returncode)\n" +
                "v=json.loads(r.stdout); n=2 if '--resume' in sys.argv else 1\n" +
                "v.update(subtype='success',result='OK',total_cost_usd=.001*n,modelUsage={'claude-sonnet-test-001':dict(inputTokens=10*n,outputTokens=2*n,cacheCreationInputTokens=5*n,cacheReadInputTokens=20*n)})\n" +
                "print(json.dumps(v))\n")
            binary.chmod(0o700)
            output = root / "report.json"
            with patch("builtins.print"):
                code = smoke_main(["--real", "--max-cost-usd", "0.05", "--claude-bin", str(binary), "--output", str(output)])
            report = json.loads(output.read_bytes())
            self.assertEqual(code, 0, report)
            self.assertTrue(report["summary"]["accounting_check_passed"])
            self.assertEqual([r["router_observation"]["classifications"] for r in report["records"]], [1, 0])
            self.assertEqual([r["total_tokens"] for r in report["records"]], [37, 37])
            self.assertAlmostEqual(report["summary"]["known_cost_usd"], .002)
            self.assertEqual(report["records"][-1]["cumulative"]["cost_usd"], .002)

    def test_no_inference_in_plan_or_smoke_dry_run(self):
        with patch("evaluation.prospective.provenance") as inspect, \
                patch("evaluation.prospective.execute") as run, patch("builtins.print"):
            self.assertEqual(main([]), 0)
            self.assertEqual(smoke_main([]), 0)
            inspect.assert_not_called()
            run.assert_not_called()

    def test_real_mode_requires_lock_and_explicit_frozen_budget(self):
        with patch("builtins.print"), patch("evaluation.prospective.execute") as run, \
                patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main(["--real"])
            with self.assertRaises(SystemExit):
                smoke_main(["--real"])
            run.assert_not_called()

    def test_quality_review_version_and_missing_data_gate_claims(self):
        report = cohort()
        reviews = {f'{r["case"]}:1:{r["arm"]}:{r["turn"]}': dict(verdict="pass", critical_regression=False)
                   for r in report["records"]}
        self.assertEqual(summarize(report)["verdict"], "inconclusive")
        self.assertEqual(summarize(report, reviews)["verdict"], "observed_sample_reduction")
        for field, value in (("client_after", dict(version="other")), ("total_tokens", None),
                             ("model_confirmed", False), ("cli_estimated_cost_usd", None),
                             ("effective_models", ["claude-sonnet-other"])):
            damaged = copy.deepcopy(report)
            damaged["records"][-1][field] = value
            summary = summarize(damaged, reviews)
            self.assertFalse(summary["comparable"])
            self.assertTrue(all(v is None for v in summary["observed_reduction_percent"].values()))
        report["records"][-1]["functional_passed"] = False
        self.assertEqual(summarize(report, reviews)["verdict"], "failed_quality")

    def test_tokens_can_increase_with_lower_price_and_human_failure_blocks_claim(self):
        report = cohort()
        reviews = {f'{r["case"]}:1:{r["arm"]}:{r["turn"]}': dict(verdict="pass", critical_regression=False)
                   for r in report["records"]}
        report["records"][-1]["total_tokens"] = 200
        result = summarize(report, reviews)
        self.assertGreater(result["observed_reduction_percent"]["cost_usd"], 0)
        self.assertLess(result["observed_reduction_percent"]["tokens"], 0)
        self.assertEqual(result["verdict"], "not_all_metrics_reduced")
        reviews["T01:1:routed:2"]["critical_regression"] = True
        self.assertEqual(summarize(report, reviews)["verdict"], "failed_quality")

    def test_duplicate_rows_cannot_satisfy_complete_design_and_failed_spend_is_kept(self):
        report = cohort()
        report["records"][-1] = copy.deepcopy(report["records"][-2])
        self.assertFalse(summarize(report)["comparable"])
        report["records"][-1]["execution_ok"] = False
        result = summarize(report)
        self.assertEqual(result["totals"]["routed"]["known_cost_usd"], .02)
        self.assertEqual(result["totals"]["routed"]["failures"], 1)

    def test_freeze_is_sanitized_and_binds_private_prompts_commits_and_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, tasks = private_manifest(root)
            protocol = json.loads(PROTOCOL.read_bytes())
            first = freeze(manifest, protocol)
            self.assertNotIn("private", json.dumps(first))
            self.assertEqual(first["manifest_sha256"], digest(manifest.read_bytes()))
            Path(tasks[0]["prompts"][0]).write_text("different private request")
            self.assertNotEqual(first, freeze(manifest, protocol))
            Path(tasks[0]["prompts"][0]).write_text(json.loads((ROOT / "evaluation/real-cases.json").read_bytes())[0]["prompt"])
            with self.assertRaises(ValueError):
                freeze(manifest, protocol)

    def test_whole_cohort_with_fake_native_preserves_pairs_and_waits_for_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, tasks = private_manifest(root)
            binary = root / "fake-native"
            binary.write_text("#!/usr/bin/env python3\nimport json,sys\n" +
                "if sys.argv[1:] == ['--version']:\n print('2.1.325 (Claude Code)'); raise SystemExit(0)\n" +
                "a=sys.argv; n=2 if '--resume' in a else 1\n" +
                "if not a[-1].endswith('\\r\\n'): raise SystemExit(4)\n" +
                "session=a[a.index('--resume' if n==2 else '--session-id')+1]\n" +
                "m=a[a.index('--model')+1]; m=m if m.startswith('claude-') else 'claude-'+m+'-test-001'\n" +
                "print(json.dumps(dict(session_id=session,subtype='success',total_cost_usd=.001*n,result='OK',modelUsage={m:dict(inputTokens=10*n,outputTokens=2*n,cacheCreationInputTokens=5*n,cacheReadInputTokens=20*n)})))\n")
            binary.chmod(0o700)
            protocol = json.loads(PROTOCOL.read_bytes())
            lock = freeze(manifest, protocol)
            output = root / "result.json"
            report = run(manifest, lock, protocol, str(binary), output, root / "runs")
            self.assertIsNone(report["stopped"], report)
            self.assertEqual(len(report["records"]), 32)
            self.assertTrue(report["summary"]["comparable"], report)
            self.assertEqual(report["summary"]["verdict"], "inconclusive")
            self.assertFalse(report["summary"]["human_review_passed"])
            self.assertAlmostEqual(sum(r["cli_estimated_cost_usd"] for r in report["records"]), .032)
            routed = [r for r in report["records"] if r["arm"] == "routed"]
            self.assertEqual(sum(r["router_observation"]["classifications"] for r in routed), 8)
            self.assertEqual([r["arm"] for r in report["records"][:8]],
                             ["baseline", "baseline", "routed", "routed", "routed", "routed", "baseline", "baseline"])
            self.assertNotIn("private request", output.read_text())
            self.assertEqual(Path(tasks[0]["project"], "example.txt").read_text(), "private code")


if __name__ == "__main__":
    unittest.main()
