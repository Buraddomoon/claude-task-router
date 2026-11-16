import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_task_router.conversation import detect
from claude_task_router.state import Store
from claude_task_router.topics import TaskContext, terms


class TopicTests(unittest.TestCase):
    def test_missing_context_abstains_and_related_object_continues(self):
        self.assertEqual(detect("Create a backup routine for local files"), "ambiguous")
        context = TaskContext.from_prompt("Fix the parser for invoice imports")
        self.assertEqual(detect("Adjust the parser to reject empty rows", context), "continue")
        self.assertEqual(detect("Build a calendar for company events", context), "new")
        self.assertEqual(detect("Do the security part now", context), "ambiguous")

    def test_resume_context_uses_only_owned_original_user_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state")
            config = root / "claude"
            path = config / "projects/test/12345678-1234-1234-1234-123456789abc.jsonl"
            path.parent.mkdir(parents=True)
            sid = path.stem
            rows = [dict(type="assistant", sessionId=sid, message=dict(content="foreign narrative")),
                    dict(type="user", sessionId="foreign", message=dict(content="foreign goal")),
                    dict(type="user", sessionId=sid, isMeta=True, message=dict(content="system message")),
                    dict(type="user", sessionId=sid, message=dict(content=[
                        dict(type="text", text="Translate navigation labels"),
                        dict(type="image", data="ignored")])),
                    dict(type="user", sessionId=sid, message=dict(content="a later request"))]
            path.write_text("\n".join(json.dumps(r) for r in rows))
            task = dict(id=sid, transcript_path=str(path))
            with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(config)}):
                context = TaskContext.from_transcript(store, task)
                self.assertEqual(context, TaskContext.from_prompt("Translate navigation labels"))
                self.assertEqual(detect("Create a backup routine for local files", context), "new")
                with patch.object(Path, "open", side_effect=AssertionError("unowned read")):
                    self.assertFalse(TaskContext.from_transcript(store,
                        dict(task, transcript_path=str(root / "foreign.jsonl"))).vocabulary)
            self.assertNotIn(b"Translate navigation labels", store.path.read_bytes())

    def test_quotes_presentation_and_scan_limits_do_not_become_topic_context(self):
        context = terms('Fix the parser. Respond only SECRET_CONSTANT.')
        self.assertIn("parser", context)
        self.assertNotIn("secret_constant", context)
        self.assertNotIn("private_literal", terms('Translate "PRIVATE_LITERAL" in the manual'))
        self.assertLessEqual(len(terms(" ".join(f"token{i}" for i in range(1000)))), 128)
