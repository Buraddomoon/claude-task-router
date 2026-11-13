import unittest

from claude_task_router.classifier import classify
from claude_task_router.config import Config, validate_model


class ClassifierTests(unittest.TestCase):
    def test_examples(self):
        cases = [
            ("Corrija o typo no README.md", "economy"),
            ("Rename the variable userNmae to userName", "economy"),
            ("Traduza este comentário para inglês", "economy"),
            ("Implemente paginação na tabela de produtos", "balanced"),
            ("Crie um sistema de roteamento automático de modelos", "balanced"),
            ("Corrija o bug no componente de busca", "balanced"),
            ("help", "balanced"),
            ("Investigue a causa raiz da falha intermitente", "advanced"),
            ("Design the architecture for a distributed system", "advanced"),
            ("Implemente autenticação OAuth", "advanced"),
            ("Plan a database migration without downtime", "advanced"),
            ("Corrija typo e faça auditoria de segurança", "advanced"),
        ]
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify(prompt).tier, expected)

    def test_custom_models_and_floor(self):
        config = Config(models=dict(economy="cheap-id", balanced="mid-id", advanced="big-id"),
                        min_tier="balanced")
        decision = classify("Fix typo", config)
        self.assertEqual(decision.model, "mid-id")
        self.assertIn("configured_minimum", decision.reasons)

    def test_empty_oversized_and_nul(self):
        for prompt in ("  ", "x" * 262145, "hi\x00"):
            with self.assertRaises(ValueError):
                classify(prompt)

    def test_bound_scan_never_economy(self):
        decision = classify("fix typo " + "x" * 1000, Config(scan_chars=100))
        self.assertEqual(decision.tier, "balanced")
        self.assertEqual(decision.scanned_chars, 100)
        self.assertIn("scan_limit_reached", decision.reasons)

    def test_config_validation(self):
        for kwargs in ({"models": {}}, {"min_tier": "cheap"}, {"scan_chars": True},
                       {"medium_words": 1500}, {"long_words": -1}):
            with self.assertRaises(ValueError):
                Config(**kwargs)
        for model in ("default", "opusplan", "opusplan[1m]", "--help", "hi there", ""):
            with self.assertRaises(ValueError):
                validate_model(model)

    def test_rules_are_deterministic(self):
        prompt = "Implemente um endpoint com testes"
        self.assertEqual(classify(prompt), classify(prompt))
