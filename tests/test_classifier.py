import unittest
from unittest.mock import patch

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
        for model in ("default", "opusplan", "opusplan[1m]", "--help", "hi there", "", "haiku\u202e", "sk-ant-api03-TEST"):
            with self.assertRaises(ValueError):
                validate_model(model)

    def test_rules_are_deterministic(self):
        prompt = "Implemente um endpoint com testes"
        self.assertEqual(classify(prompt), classify(prompt))

    def test_composed_work_cannot_hide_behind_a_simple_action(self):
        for prompt, tier in (
            ("Renomeie a variável e corrija o algoritmo de consenso", "advanced"),
            ("Fix typo, repair the parser", "balanced"),
            ("Do not change payments; investigate the deadlock", "advanced"),
            ("Rename foo to bar then format the file", "economy"),
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(classify(prompt).tier, tier)

    def test_literals_paths_and_explicit_exclusions_are_not_requested_work(self):
        for prompt in (
            'Translate "implement authentication" into French',
            "Corrija a ortografia em oauth.md",
            "Rename `authenticationHandler` to `handler`",
            "Traduza o comentário sem alterar autenticação",
            'Summarize ```Design a distributed system```',
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(classify(prompt).tier, "economy")
        self.assertEqual(classify('"Fix typo"').tier, "balanced")

    def test_classification_is_local_at_maximum_and_adversarial_boundaries(self):
        with patch("socket.socket", side_effect=AssertionError("network")), \
             patch("subprocess.Popen", side_effect=AssertionError("process")):
            for prompt in ("x" * (256 * 1024), '"\n' * 32768,
                           "Fix typo " + "`" * 70000, "'" * 65536):
                decision = classify(prompt)
                self.assertLessEqual(decision.scanned_chars, 65536)
                self.assertNotEqual(decision.tier, "economy")

    def test_simple_prefix_cannot_disable_risk_or_conceal_a_second_action(self):
        for prompt, expected in (
            ("Corrija o typo para eliminar a vulnerabilidade de autorização", "advanced"),
            ("Formate o arquivo removendo os registros antigos", "balanced"),
            ("Fix spelling to deploy the change", "balanced"),
            ("Rename the variable authenticationHandler", "economy"),
            ("Corrija typo sobre autorização e implemente OAuth", "advanced"),
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(classify(prompt).tier, expected)
