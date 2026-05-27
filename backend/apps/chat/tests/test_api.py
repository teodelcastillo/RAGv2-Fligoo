from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.chat.api.views import _chat_retrieval_params, _chunk_ids_from_citations
from apps.chat.models import ChatSession
from apps.chat.services.rag import RetrievalResult
from apps.chat.services.query_analysis import COVERAGE_MODE_ALL, classify_query
from apps.document.models import Document, SmartChunk

User = get_user_model()


class ChatAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="secret123", username="owner"
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", password="secret123", username="other"
        )
        self.document = Document.objects.create(
            owner=self.user, name="Doc 1", slug="doc-1", is_public=False
        )
        self.public_document = Document.objects.create(
            owner=self.other_user, name="Public Doc", slug="public-doc", is_public=True
        )
        self.client.force_authenticate(self.user)

    def test_create_session_with_owned_document(self):
        url = reverse("chat-session-list")
        payload = {
            "title": "Investigación",
            "document_slugs": ["doc-1"],
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["document_slugs"], ["doc-1"])

    def test_create_session_rejects_forbidden_documents(self):
        url = reverse("chat-session-list")
        payload = {
            "title": "No permitido",
            "document_slugs": ["non-existent"],
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_session_rejects_too_many_documents(self):
        docs = [
            Document.objects.create(
                owner=self.user,
                name=f"Doc {i}",
                slug=f"doc-{i}",
            )
            for i in range(25)
        ]
        url = reverse("chat-session-list")
        payload = {
            "title": "Demasiado amplia",
            "document_slugs": [doc.slug for doc in docs],
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("máximo", str(response.data))

    def test_repository_panorama_query_uses_all_docs_policy(self):
        analysis = classify_query(
            "Necesito saber en rasgos generales de que trata este repositorio"
        )
        self.assertEqual(analysis.coverage_mode, COVERAGE_MODE_ALL)

        session = ChatSession.objects.create(
            owner=self.user,
            title="Repositorio",
        )
        docs = [
            Document.objects.create(
                owner=self.user,
                name=f"Repo Doc {i}",
                slug=f"repo-doc-{i}",
            )
            for i in range(17)
        ]
        session.allowed_documents.set(docs)

        params = _chat_retrieval_params(
            session,
            "Necesito saber en rasgos generales de que trata este repositorio",
        )
        self.assertEqual(params["total_limit"], 17)
        self.assertEqual(params["top_n"], 17)
        self.assertEqual(params["max_chunks_per_doc"], 1)

    @patch("apps.chat.services.rag.fetch_relevant_chunks")
    @patch("apps.document.utils.client_openia.generate_chat_completion")
    def test_create_message_returns_assistant_response(
        self, mock_completion, mock_fetch_chunks
    ):
        mock_completion.return_value = ("Respuesta generada", {"total_tokens": 10})

        chunk = SmartChunk.objects.create(
            document=self.document,
            chunk_index=0,
            content="Información relevante",
            token_count=5,
        )
        mock_fetch_chunks.return_value = [chunk]

        session = ChatSession.objects.create(
            owner=self.user,
            title="Sesión",
        )
        session.allowed_documents.add(self.document)

        url = reverse("chat-message-list")
        payload = {"session": session.id, "content": "¿Qué dice el documento?"}

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("assistant_message", response.data)
        self.assertEqual(
            response.data["assistant_message"]["content"], "Respuesta generada"
        )

    def test_list_messages_requires_session_param(self):
        session = ChatSession.objects.create(owner=self.user, title="Sesión")
        url = reverse("chat-message-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_messages_filters_by_session(self):
        session_a = ChatSession.objects.create(owner=self.user, title="A")
        session_b = ChatSession.objects.create(owner=self.user, title="B")
        from apps.chat.models import ChatMessage, MessageRole

        ChatMessage.objects.create(
            session=session_a,
            role=MessageRole.USER,
            content="Hola A",
        )
        ChatMessage.objects.create(
            session=session_b,
            role=MessageRole.USER,
            content="Hola B",
        )

        url = reverse("chat-message-list")
        response = self.client.get(url, {"session": session_a.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["content"], "Hola A")
        self.assertEqual(response.data[0]["session"], session_a.id)

    def test_chunk_ids_from_citations_keeps_only_cited_chunks(self):
        retrieval = RetrievalResult()
        retrieval.chunks = [type("Chunk", (), {"id": 11})(), type("Chunk", (), {"id": 22})()]
        ids = _chunk_ids_from_citations("Respuesta [#2] con cita puntual.", retrieval)
        self.assertEqual(ids, [22])

    def test_chunk_ids_from_citations_falls_back_when_no_citations(self):
        retrieval = RetrievalResult()
        retrieval.chunks = [type("Chunk", (), {"id": 11})(), type("Chunk", (), {"id": 22})()]
        ids = _chunk_ids_from_citations("Respuesta sin marcadores de cita.", retrieval)
        self.assertEqual(ids, [11, 22])

    @patch("apps.chat.services.rag.lexical_search")
    @patch("apps.chat.services.rag.fetch_relevant_chunks")
    @patch("apps.document.utils.client_openia.generate_chat_completion")
    def test_create_message_without_evidence_returns_empty_chunk_ids(
        self, mock_completion, mock_fetch_chunks, mock_lexical
    ):
        mock_completion.return_value = ("Respuesta general sin evidencia documental.", {"total_tokens": 10})
        mock_fetch_chunks.return_value = []
        mock_lexical.return_value = []

        session = ChatSession.objects.create(owner=self.user, title="Global")
        url = reverse("chat-message-list")
        payload = {"session": session.id, "content": "¿Qué dice el Acuerdo de París?"}

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["assistant_message"]["chunk_ids"], [])























