import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class CorpusTests(unittest.TestCase):
    def test_frozen_corpus_has_disjoint_balanced_splits_and_rationales(self):
        raw = (ROOT / "evaluation/corpus.json").read_bytes()
        cases = json.loads(raw)
        baseline = json.loads((ROOT / "evaluation/baseline-development.json").read_text())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), baseline["corpus_sha256"])
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertEqual(len(cases), len({case["prompt"] for case in cases}))
        for split in ("development", "evaluation"):
            subset = [case for case in cases if case["split"] == split]
            self.assertEqual(len(subset), 28)
            self.assertEqual({case["tier"] for case in subset}, {"economy", "balanced", "advanced"})
            for category in ("simple", "common", "complex", "composed", "negative", "reference", "quoted"):
                for language in ("pt", "en"):
                    group = [case for case in subset
                             if case["category"] == category and case["language"] == language]
                    self.assertEqual(len(group), 2, (split, category, language))
                    self.assertTrue(all(case["rationale"].strip() for case in group))


if __name__ == "__main__":
    unittest.main()
