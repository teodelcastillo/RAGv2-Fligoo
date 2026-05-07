"""
Tests for Sprint 5: Ecofilia Copilot + project structure.

Covers:
- ProjectStructureTemplate / ProjectSection models.
- initialize_project_structure service function.
- Copilot system prompt builder.
- Copilot tool executors (search_documents, calculate_ghg, get_document_list,
  run_skill, get_execution_history, get_project_structure, update_section_status).
- Copilot message processing (generate_with_tools mock).
- API endpoints: structure, copilot sessions, copilot messages.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.chat.models import ChatSession, ChatSessionType
from apps.document.models import Document
from apps.project.models import (
    Project,
    ProjectDocument,
    ProjectSection,
    ProjectSectionStatus,
    ProjectStructureSection,
    ProjectStructureTemplate,
)

User = get_user_model()

_chunk_id_counter = 0


def _make_chunk(doc, index=0):
    global _chunk_id_counter
    _chunk_id_counter += 1
    return SimpleNamespace(
        id=_chunk_id_counter, document=doc, chunk_index=index, content="chunk"
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class StructureTemplateModelTestCase(TestCase):
    def test_create_template_with_sections(self):
        template = ProjectStructureTemplate.objects.create(
            name="GEI Test", slug="gei-test", description="Test template."
        )
        ProjectStructureSection.objects.create(
            template=template, title="Scope", position=1
        )
        ProjectStructureSection.objects.create(
            template=template, title="Data", position=2
        )
        self.assertEqual(template.sections.count(), 2)
        self.assertEqual(str(template), "GEI Test")


class ProjectSectionModelTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="sec@example.com", password="secret123", username="sec"
        )
        self.project = Project.objects.create(owner=self.user, name="SecProject")

    def test_create_project_section(self):
        section = ProjectSection.objects.create(
            project=self.project, title="Intro", position=1
        )
        self.assertEqual(section.status, ProjectSectionStatus.NOT_STARTED)

    def test_status_transitions(self):
        section = ProjectSection.objects.create(
            project=self.project, title="Intro", position=1
        )
        section.status = ProjectSectionStatus.IN_PROGRESS
        section.save(update_fields=["status"])
        section.refresh_from_db()
        self.assertEqual(section.status, ProjectSectionStatus.IN_PROGRESS)

    def test_unique_position_per_project(self):
        ProjectSection.objects.create(
            project=self.project, title="A", position=1
        )
        with self.assertRaises(Exception):
            ProjectSection.objects.create(
                project=self.project, title="B", position=1
            )


# ---------------------------------------------------------------------------
# Service: initialize_project_structure
# ---------------------------------------------------------------------------


class InitializeProjectStructureTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="init@example.com", password="secret123", username="init"
        )
        self.project = Project.objects.create(owner=self.user, name="InitProject")
        self.template = ProjectStructureTemplate.objects.create(
            name="Template", slug="init-template"
        )
        ProjectStructureSection.objects.create(
            template=self.template, title="Step A", position=1, description="Do A."
        )
        ProjectStructureSection.objects.create(
            template=self.template, title="Step B", position=2, description="Do B."
        )

    def test_initializes_sections_from_template(self):
        from apps.chat.services.copilot import initialize_project_structure

        sections = initialize_project_structure(self.project, "init-template")
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].title, "Step A")
        self.assertEqual(sections[1].title, "Step B")
        self.project.refresh_from_db()
        self.assertEqual(self.project.structure_template, self.template)

    def test_reinitialize_replaces_existing(self):
        from apps.chat.services.copilot import initialize_project_structure

        ProjectSection.objects.create(
            project=self.project, title="Old", position=1
        )
        sections = initialize_project_structure(self.project, "init-template")
        self.assertEqual(len(sections), 2)
        self.assertEqual(ProjectSection.objects.filter(project=self.project).count(), 2)


# ---------------------------------------------------------------------------
# Copilot system prompt
# ---------------------------------------------------------------------------


class CopilotSystemPromptTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="prompt@example.com", password="secret123", username="prompt"
        )
        self.project = Project.objects.create(
            owner=self.user,
            name="PromptProject",
            context_notes={"company": "Acme Corp", "sector": "Manufacturing"},
        )
        self.doc = Document.objects.create(
            owner=self.user, name="Report", slug="report-prompt"
        )
        ProjectDocument.objects.create(
            project=self.project, document=self.doc, added_by=self.user
        )
        ProjectSection.objects.create(
            project=self.project, title="Scope", position=1,
            status=ProjectSectionStatus.COMPLETED,
        )
        ProjectSection.objects.create(
            project=self.project, title="Data", position=2,
            status=ProjectSectionStatus.IN_PROGRESS, notes="Missing Q4",
        )

    def test_includes_project_name(self):
        from apps.chat.services.copilot import build_copilot_system_prompt

        documents = Document.objects.filter(id=self.doc.id)
        prompt = build_copilot_system_prompt(self.project, documents)
        self.assertIn("PromptProject", prompt)

    def test_includes_context_notes(self):
        from apps.chat.services.copilot import build_copilot_system_prompt

        documents = Document.objects.filter(id=self.doc.id)
        prompt = build_copilot_system_prompt(self.project, documents)
        self.assertIn("Acme Corp", prompt)
        self.assertIn("Manufacturing", prompt)

    def test_includes_structure_with_statuses(self):
        from apps.chat.services.copilot import build_copilot_system_prompt

        documents = Document.objects.filter(id=self.doc.id)
        prompt = build_copilot_system_prompt(self.project, documents)
        self.assertIn("[COMPLETADO] Scope", prompt)
        self.assertIn("[EN PROGRESO] Data", prompt)
        self.assertIn("Missing Q4", prompt)

    def test_includes_document_list(self):
        from apps.chat.services.copilot import build_copilot_system_prompt

        documents = Document.objects.filter(id=self.doc.id)
        prompt = build_copilot_system_prompt(self.project, documents)
        self.assertIn("report-prompt", prompt)


# ---------------------------------------------------------------------------
# Copilot tools
# ---------------------------------------------------------------------------


class CopilotSearchDocumentsToolTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="search@example.com", password="secret123", username="search"
        )
        self.project = Project.objects.create(owner=self.user, name="SearchProject")
        self.doc = Document.objects.create(
            owner=self.user, name="Doc", slug="doc-search"
        )
        ProjectDocument.objects.create(
            project=self.project, document=self.doc, added_by=self.user
        )

    @patch("apps.chat.services.copilot_tools.build_context_block")
    @patch("apps.chat.services.copilot_tools.fetch_relevant_chunks")
    def test_returns_context_block(self, mock_fetch, mock_build):
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_search_documents

        chunk = _make_chunk(self.doc)
        mock_fetch.return_value = [chunk]
        mock_build.return_value = "Context block content."

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.filter(id=self.doc.id),
        )
        result = _execute_search_documents({"query": "emissions"}, ctx)
        self.assertEqual(result, "Context block content.")
        self.assertEqual(len(ctx.additional_chunks), 1)

    def test_empty_query_returns_error(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_search_documents

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.filter(id=self.doc.id),
        )
        result = _execute_search_documents({"query": ""}, ctx)
        self.assertIn("Error", result)


class CopilotRunSkillToolTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="rskill@example.com", password="secret123", username="rskill"
        )
        self.project = Project.objects.create(owner=self.user, name="SkillProject")
        self.doc = Document.objects.create(
            owner=self.user, name="Doc", slug="doc-rskill"
        )
        ProjectDocument.objects.create(
            project=self.project, document=self.doc, added_by=self.user
        )

    @patch("apps.skill.services.execute_skill")
    def test_runs_quick_skill(self, mock_execute):
        from apps.skill.models import Skill, SkillExecution, SkillType, ExecutionStatus
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_run_skill

        skill = Skill.objects.create(
            owner=self.user,
            name="Quick Analysis",
            skill_type=SkillType.QUICK,
            allowed_contexts=["project"],
            prompt_template="Analyze {{context}}",
        )

        mock_execute.return_value = SimpleNamespace(
            status=ExecutionStatus.COMPLETED,
            output="Analysis result.",
            error_message="",
        )

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.filter(id=self.doc.id),
        )
        result = _execute_run_skill({"skill_slug": skill.slug}, ctx)
        self.assertIn("Analysis result.", result)
        mock_execute.assert_called_once()

    def test_rejects_copilot_skill(self):
        from apps.skill.models import Skill, SkillType
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_run_skill

        skill = Skill.objects.create(
            owner=self.user,
            name="Copilot Skill",
            skill_type=SkillType.COPILOT,
            allowed_contexts=["project"],
            system_prompt="ESG.",
        )

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.filter(id=self.doc.id),
        )
        result = _execute_run_skill({"skill_slug": skill.slug}, ctx)
        self.assertIn("cannot be run inline", result)

    def test_unknown_skill_returns_error(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_run_skill

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.filter(id=self.doc.id),
        )
        result = _execute_run_skill({"skill_slug": "nonexistent"}, ctx)
        self.assertIn("not found", result)


class CopilotProjectStructureToolTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="struct@example.com", password="secret123", username="struct"
        )
        self.project = Project.objects.create(owner=self.user, name="StructProject")
        ProjectSection.objects.create(
            project=self.project, title="Scope", position=1,
            status=ProjectSectionStatus.COMPLETED,
        )
        ProjectSection.objects.create(
            project=self.project, title="Data", position=2,
            status=ProjectSectionStatus.NOT_STARTED,
        )

    def test_get_project_structure(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_get_project_structure

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.none(),
        )
        result = _execute_get_project_structure({}, ctx)
        self.assertIn("COMPLETADO", result)
        self.assertIn("PENDIENTE", result)
        self.assertIn("Scope", result)

    def test_update_section_status(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_update_section_status

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.none(),
        )
        result = _execute_update_section_status(
            {"section_position": 2, "status": "in_progress", "notes": "Started."}, ctx
        )
        self.assertIn("updated", result)
        section = ProjectSection.objects.get(project=self.project, position=2)
        self.assertEqual(section.status, ProjectSectionStatus.IN_PROGRESS)
        self.assertEqual(section.notes, "Started.")

    def test_update_invalid_position(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, _execute_update_section_status

        ctx = CopilotToolContext(
            user=self.user,
            project=self.project,
            allowed_documents=Document.objects.none(),
        )
        result = _execute_update_section_status(
            {"section_position": 99, "status": "completed"}, ctx
        )
        self.assertIn("No section", result)


class CopilotToolDispatcherTestCase(TestCase):
    def test_unknown_tool(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, execute_copilot_tool

        user = User.objects.create_user(
            email="disp@example.com", password="secret123", username="disp"
        )
        project = Project.objects.create(owner=user, name="DispProject")
        ctx = CopilotToolContext(
            user=user, project=project, allowed_documents=Document.objects.none(),
        )
        result = execute_copilot_tool("bogus_tool", "{}", ctx)
        self.assertIn("Unknown tool", result)

    def test_invalid_json_args(self):
        from apps.chat.services.copilot_tools import CopilotToolContext, execute_copilot_tool

        user = User.objects.create_user(
            email="json@example.com", password="secret123", username="jsonuser"
        )
        project = Project.objects.create(owner=user, name="JsonProject")
        ctx = CopilotToolContext(
            user=user, project=project, allowed_documents=Document.objects.none(),
        )
        result = execute_copilot_tool("search_documents", "not json!", ctx)
        self.assertIn("Invalid JSON", result)


# ---------------------------------------------------------------------------
# Copilot message processing (end-to-end with mocks)
# ---------------------------------------------------------------------------


class CopilotMessageProcessingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="msg@example.com", password="secret123", username="msg"
        )
        self.project = Project.objects.create(
            owner=self.user, name="MsgProject",
            context_notes={"company": "TestCo"},
            copilot_enabled=True,
        )
        self.doc = Document.objects.create(
            owner=self.user, name="Doc", slug="doc-msg"
        )
        ProjectDocument.objects.create(
            project=self.project, document=self.doc, added_by=self.user
        )
        self.session = ChatSession.objects.create(
            owner=self.user,
            project=self.project,
            session_type=ChatSessionType.COPILOT,
            title="Test Copilot",
        )
        self.session.allowed_documents.set([self.doc])

    @patch("apps.chat.services.copilot.generate_with_tools")
    def test_process_copilot_message(self, mock_gen):
        from apps.chat.services.copilot import process_copilot_message

        mock_gen.return_value = ("Here is my analysis.", {"total_tokens": 50})

        text, metadata, chunk_ids = process_copilot_message(
            self.session, "What emissions data do we have?", self.user
        )

        self.assertEqual(text, "Here is my analysis.")
        self.assertTrue(metadata["copilot"])
        mock_gen.assert_called_once()
        call_args = mock_gen.call_args
        messages = call_args.args[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("MsgProject", messages[0]["content"])
        self.assertIn("TestCo", messages[0]["content"])

    @patch("apps.chat.services.copilot.generate_with_tools")
    def test_no_project_raises_error(self, mock_gen):
        from apps.chat.services.copilot import process_copilot_message

        session = ChatSession.objects.create(
            owner=self.user,
            session_type=ChatSessionType.COPILOT,
            title="No Project",
        )
        with self.assertRaises(ValueError):
            process_copilot_message(session, "hello", self.user)


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class StructureTemplateAPITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="tmpl@example.com", password="secret123", username="tmpl"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.template = ProjectStructureTemplate.objects.create(
            name="API Template", slug="api-template", description="Desc."
        )
        ProjectStructureSection.objects.create(
            template=self.template, title="S1", position=1
        )

    def test_list_templates(self):
        response = self.client.get("/api/projects/structure-templates/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) >= 1)

    def test_retrieve_template(self):
        response = self.client.get("/api/projects/structure-templates/api-template/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slug"], "api-template")
        self.assertEqual(len(response.data["sections"]), 1)


class ProjectStructureAPITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="pstr@example.com", password="secret123", username="pstr"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="StructAPIProject")
        self.template = ProjectStructureTemplate.objects.create(
            name="Struct Template", slug="struct-template"
        )
        ProjectStructureSection.objects.create(
            template=self.template, title="Phase 1", position=1
        )
        ProjectStructureSection.objects.create(
            template=self.template, title="Phase 2", position=2
        )

    def test_get_empty_structure(self):
        response = self.client.get(
            f"/api/projects/{self.project.slug}/structure/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sections"], [])

    def test_initialize_structure(self):
        response = self.client.put(
            f"/api/projects/{self.project.slug}/structure/initialize/",
            {"template_slug": "struct-template"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["title"], "Phase 1")

    def test_update_section_status(self):
        ProjectSection.objects.create(
            project=self.project, title="Phase 1", position=1
        )
        response = self.client.patch(
            f"/api/projects/{self.project.slug}/structure/sections/1/",
            {"status": "in_progress", "notes": "Working on it."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "in_progress")
        self.assertEqual(response.data["notes"], "Working on it.")


class CopilotSessionAPITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="csess@example.com", password="secret123", username="csess"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(
            owner=self.user, name="CopilotSessionProject", copilot_enabled=True,
        )
        self.doc = Document.objects.create(
            owner=self.user, name="Doc", slug="doc-csess"
        )
        ProjectDocument.objects.create(
            project=self.project, document=self.doc, added_by=self.user
        )

    def test_create_copilot_session(self):
        response = self.client.post(
            f"/api/projects/{self.project.slug}/copilot/sessions/"
        )
        self.assertEqual(response.status_code, 201)
        session = ChatSession.objects.get(pk=response.data["id"])
        self.assertEqual(session.session_type, ChatSessionType.COPILOT)
        self.assertEqual(session.project, self.project)

    def test_list_copilot_sessions(self):
        ChatSession.objects.create(
            owner=self.user, project=self.project,
            session_type=ChatSessionType.COPILOT, title="S1",
        )
        ChatSession.objects.create(
            owner=self.user, project=self.project,
            session_type=ChatSessionType.STANDARD, title="Not copilot",
        )
        response = self.client.get(
            f"/api/projects/{self.project.slug}/copilot/sessions/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_other_user_cannot_create_session(self):
        other = User.objects.create_user(
            email="other@example.com", password="secret123", username="other"
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other)
        response = other_client.post(
            f"/api/projects/{self.project.slug}/copilot/sessions/"
        )
        self.assertEqual(response.status_code, 404)


class CopilotMessageAPITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="cmsg@example.com", password="secret123", username="cmsg"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(
            owner=self.user, name="CopilotMsgProject",
            context_notes={"company": "TestCo"},
        )
        self.doc = Document.objects.create(
            owner=self.user, name="Doc", slug="doc-cmsg"
        )
        ProjectDocument.objects.create(
            project=self.project, document=self.doc, added_by=self.user
        )
        self.session = ChatSession.objects.create(
            owner=self.user, project=self.project,
            session_type=ChatSessionType.COPILOT, title="Test",
        )
        self.session.allowed_documents.set([self.doc])

    @patch("apps.chat.services.copilot.generate_with_tools")
    def test_send_copilot_message(self, mock_gen):
        mock_gen.return_value = ("Copilot response.", {"total_tokens": 10})
        response = self.client.post(
            f"/api/projects/{self.project.slug}/copilot/messages/",
            {"session": self.session.id, "content": "Help me with scope 1."},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["assistant_message"]["content"], "Copilot response."
        )
        self.assertEqual(response.data["user_message"]["content"], "Help me with scope 1.")

    @patch("apps.chat.services.copilot.generate_with_tools")
    def test_send_message_without_session_uses_latest(self, mock_gen):
        mock_gen.return_value = ("Response.", {"total_tokens": 5})
        response = self.client.post(
            f"/api/projects/{self.project.slug}/copilot/messages/",
            {"content": "What's next?"},
        )
        self.assertEqual(response.status_code, 201)

    def test_send_message_no_session_returns_400(self):
        self.session.delete()
        response = self.client.post(
            f"/api/projects/{self.project.slug}/copilot/messages/",
            {"content": "Hello"},
        )
        self.assertEqual(response.status_code, 400)
