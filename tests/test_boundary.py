from datetime import datetime, timedelta, timezone
import unittest

from claude_task_router.boundary import choose


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.instant = datetime.now(timezone.utc)
        self.task = dict(created_at=self.instant.isoformat(), last_exit_code=0)

    def test_explicit_continuations_and_new_topics_in_both_languages(self):
        for prompt in ("Continue com os testes", "Retome a tarefa", "Agora valide o resultado",
                       "Now test it", "And add tests", "Na mesma tarefa, corrija o parser"):
            self.assertEqual(choose(prompt, self.task, instant=self.instant)[0], "resume", prompt)
        for prompt in ("Nova tarefa: corrija typo", "New topic: fix parser", "Implemente OAuth",
                       "Agora implemente pagamentos", 'Traduza "continue"', "Open a new file"):
            self.assertEqual(choose(prompt, self.task, instant=self.instant)[0], "new", prompt)

    def test_missing_task_old_failure_and_overrides_are_not_silent_fallbacks(self):
        with self.assertRaises(ValueError):
            choose("Continue", None)
        with self.assertRaises(ValueError):
            choose("Continue", None, "continue")
        self.task["last_launched_at"] = (self.instant - timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "não é recente"):
            choose("Continue", self.task, instant=self.instant)
        self.assertEqual(choose("Continue", self.task, "continue")[0], "resume")
        self.task.pop("last_launched_at")
        self.task["last_exit_code"] = 7
        with self.assertRaisesRegex(ValueError, "falhou"):
            choose("Continue", self.task, instant=self.instant)
        self.assertEqual(choose("Continue", self.task, "new")[0], "new")
