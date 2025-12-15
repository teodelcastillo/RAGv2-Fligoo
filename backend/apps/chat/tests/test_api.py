from unittest.mock import patch, MagicMock

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

    def test_create_session_without_documents(self):
        """Test que se puede crear una sesión sin documentos asignados"""
        url = reverse("chat-session-list")
        payload = {
            "title": "Sesión general",
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["document_slugs"], [])

    @patch("apps.chat.services.rag.fetch_relevant_chunks")
    @patch("apps.document.utils.client_openia.generate_chat_completion")
    @patch("apps.chat.services.rag.accessible_documents_queryset")
    def test_global_rag_when_no_documents_assigned(
        self, mock_accessible_docs, mock_completion, mock_fetch_chunks
    ):
        """Test que sesión sin documentos usa RAG global sobre biblioteca accesible"""
        mock_completion.return_value = ("Respuesta con RAG global", {"total_tokens": 10})
        
        # Mock del queryset de documentos accesibles
        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        mock_accessible_docs.return_value = mock_qs

        chunk = SmartChunk.objects.create(
            document=self.public_document,
            chunk_index=0,
            content="Información pública",
            token_count=5,
        )
        mock_fetch_chunks.return_value = [chunk]

        # Crear sesión sin documentos
        session = ChatSession.objects.create(
            owner=self.user,
            title="Sesión global",
        )

        url = reverse("chat-message-list")
        payload = {"session": session.id, "content": "¿Qué información hay disponible?"}

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verificar que se llamó a accessible_documents_queryset
        mock_accessible_docs.assert_called_once_with(self.user)
        
        # Verificar que fetch_relevant_chunks se llamó con el queryset global
        mock_fetch_chunks.assert_called_once()
        call_args = mock_fetch_chunks.call_args
        self.assertEqual(call_args.kwargs["allowed_documents"], mock_qs)

    @patch("apps.chat.services.rag.fetch_relevant_chunks")
    @patch("apps.document.utils.client_openia.generate_chat_completion")
    @patch("apps.chat.services.rag.suggest_related_documents")
    def test_recommendations_in_message_metadata(
        self, mock_suggest, mock_completion, mock_fetch_chunks
    ):
        """Test que las recomendaciones aparecen en metadata del mensaje asistente"""
        mock_completion.return_value = ("Respuesta", {"total_tokens": 10})
        
        chunk = SmartChunk.objects.create(
            document=self.document,
            chunk_index=0,
            content="Información relevante",
            token_count=5,
        )
        mock_fetch_chunks.return_value = [chunk]

        # Mock de recomendaciones
        mock_suggest.return_value = [
            {
                "id": self.public_document.id,
                "slug": self.public_document.slug,
                "name": self.public_document.name,
                "relevance_score": 3,
            }
        ]

        session = ChatSession.objects.create(
            owner=self.user,
            title="Sesión",
        )
        session.allowed_documents.add(self.document)

        url = reverse("chat-message-list")
        payload = {"session": session.id, "content": "¿Qué dice el documento?"}

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        assistant_message = response.data["assistant_message"]
        self.assertIn("recommended_documents", assistant_message)
        self.assertEqual(len(assistant_message["recommended_documents"]), 1)
        self.assertEqual(
            assistant_message["recommended_documents"][0]["slug"], "public-doc"
        )

    def test_add_documents_to_session(self):
        """Test que se pueden añadir documentos a una sesión existente"""
        session = ChatSession.objects.create(
            owner=self.user,
            title="Sesión inicial",
        )
        session.allowed_documents.add(self.document)

        url = reverse("chat-session-add-documents", kwargs={"pk": session.id})
        payload = {"document_slugs": [self.public_document.slug]}

        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verificar que ambos documentos están ahora en la sesión
        self.assertIn("doc-1", response.data["document_slugs"])
        self.assertIn("public-doc", response.data["document_slugs"])

    def test_add_documents_forbidden_for_other_user(self):
        """Test que no se pueden añadir documentos a sesión de otro usuario"""
        session = ChatSession.objects.create(
            owner=self.other_user,
            title="Sesión de otro",
        )

        url = reverse("chat-session-add-documents", kwargs={"pk": session.id})
        payload = {"document_slugs": [self.document.slug]}

        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_documents_rejects_inaccessible_documents(self):
        """Test que no se pueden añadir documentos sin permisos"""
        other_private_doc = Document.objects.create(
            owner=self.other_user,
            name="Privado",
            slug="privado",
            is_public=False,
        )

        session = ChatSession.objects.create(
            owner=self.user,
            title="Sesión",
        )

        url = reverse("chat-session-add-documents", kwargs={"pk": session.id})
        payload = {"document_slugs": [other_private_doc.slug]}

        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)














