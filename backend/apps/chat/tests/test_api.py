from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.chat.models import ChatSession
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














