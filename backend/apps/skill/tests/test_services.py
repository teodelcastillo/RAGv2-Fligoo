from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.document.models import Document
from apps.project.models import Project, ProjectDocument
from apps.skill.models import Skill, SkillExecution, SkillType
from apps.skill.services import execute_skill


User = get_user_model()


class SkillRunnerServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="secret123",
            username="owner",
        )
        self.project = Project.objects.create(owner=self.user, name="Project 1")
        self.doc_a = Document.objects.create(owner=self.user, name="Doc A", slug="doc-a")
        self.doc_b = Document.objects.create(owner=self.user, name="Doc B", slug="doc-b")
        ProjectDocument.objects.create(project=self.project, document=self.doc_a, added_by=self.user)
        ProjectDocument.objects.create(project=self.project, document=self.doc_b, added_by=self.user)

        self.skill = Skill.objects.create(
            owner=self.user,
            name="Goal Comparison",
            skill_type=SkillType.QUICK,
            allowed_contexts=["project"],
            system_prompt="Be precise.",
            prompt_template="Documents:\n{{context}}\n\n{{extra_instructions}}",
            comparative_mode_enabled=True,
            strict_missing_evidence=True,
            retrieval_strategy="global",
            k_per_doc=2,
            total_limit=10,
            max_per_doc_after_rerank=3,
        )

    @patch("apps.skill.services.generate_chat_completion")
    @patch("apps.skill.services.fetch_relevant_chunks")
    def test_quick_comparative_mode_enforces_prompt_and_hybrid_strategy(
        self, mock_fetch_chunks, mock_completion
    ):
        chunk_a = SimpleNamespace(document=self.doc_a, chunk_index=0, content="Goal A")
        chunk_b = SimpleNamespace(document=self.doc_b, chunk_index=1, content="Goal B")
        mock_fetch_chunks.return_value = [chunk_a, chunk_b]
        mock_completion.return_value = ("Result", {"total_tokens": 42})

        execution = SkillExecution.objects.create(
            skill=self.skill,
            owner=self.user,
            project=self.project,
            extra_instructions="Compare targets by criterion.",
        )

        execute_skill(execution)
        execution.refresh_from_db()

        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.metadata["retrieval_strategy_used"], "hybrid_per_document")
        self.assertTrue(execution.metadata["comparative_mode_enabled"])
        self.assertEqual(execution.metadata["docs_total"], 2)
        self.assertEqual(execution.metadata["docs_covered"], 2)

        mock_fetch_chunks.assert_called_once()
        fetch_kwargs = mock_fetch_chunks.call_args.kwargs
        self.assertEqual(fetch_kwargs["retrieval_strategy"], "hybrid_per_document")
        self.assertEqual(fetch_kwargs["k_per_doc"], 2)
        self.assertEqual(fetch_kwargs["total_limit"], 10)
        self.assertEqual(fetch_kwargs["max_chunks_per_doc"], 3)

        self.assertTrue(mock_completion.called)
        rendered_prompt = mock_completion.call_args.args[0][1]["content"]
        self.assertIn("Present findings by document first", rendered_prompt)
        self.assertIn("Sin evidencia en fuentes provistas", rendered_prompt)
