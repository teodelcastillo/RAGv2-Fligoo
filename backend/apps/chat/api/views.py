from __future__ import annotations

import logging
import os

from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.chat.api.serializers import (
    ChatMessageCreateSerializer,
    ChatMessageSerializer,
    ChatSessionCreateSerializer,
    ChatSessionSerializer,
)
from apps.chat.models import ChatMessage, ChatSession, MessageRole
from apps.chat.services.rag import build_context_block, fetch_relevant_chunks
from apps.document.utils.client_openia import generate_chat_completion

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = int(os.environ.get("CHAT_HISTORY_MESSAGES", "10"))


class ChatSessionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        qs = ChatSession.objects.prefetch_related("allowed_documents")
        if self.request.user.is_staff:
            return qs
        return qs.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return ChatSessionCreateSerializer
        return ChatSessionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save(owner=request.user)
        output = ChatSessionSerializer(
            session, context=self.get_serializer_context()
        )
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)


class ChatMessageViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatMessageSerializer

    def get_queryset(self):
        qs = (
            ChatMessage.objects.select_related("session", "session__owner")
            .prefetch_related("session__allowed_documents")
            .order_by("created_at")
        )
        if self.request.user.is_staff:
            return qs
        return qs.filter(session__owner=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = ChatMessageCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.validated_data["session"]
        content = serializer.validated_data["content"]

        allowed_docs = session.allowed_documents.all()
        chunks = []
        context_block = None

        # Si hay documentos disponibles, buscar chunks relevantes
        if allowed_docs.exists():
            chunks = fetch_relevant_chunks(
                user=request.user,
                query_text=content,
                allowed_documents=allowed_docs,
            )
            context_block = build_context_block(chunks)

        # Construir mensajes base
        base_messages = [
            {"role": MessageRole.SYSTEM, "content": session.system_prompt.strip()},
        ]
        
        # Si hay contexto de documentos, agregarlo con prioridad
        if context_block:
            base_messages.append(
                {
                    "role": MessageRole.SYSTEM,
                    "content": (
                        "Utiliza exclusivamente el siguiente contexto para responder. "
                        "Si no hay suficiente información en el contexto, responde que no se encontró."
                        f"\n\n{context_block}"
                    ),
                }
            )

        history_qs = (
            session.messages.order_by("-created_at")
            .exclude(role=MessageRole.SYSTEM)
            [:MAX_HISTORY_MESSAGES]
        )
        history_messages = [
            {"role": message.role, "content": message.content}
            for message in reversed(list(history_qs))
        ]
        messages = base_messages + history_messages
        messages.append({"role": MessageRole.USER, "content": content})

        with transaction.atomic():
            user_message = ChatMessage.objects.create(
                session=session,
                role=MessageRole.USER,
                content=content,
            )

            try:
                answer_text, usage = generate_chat_completion(
                    messages,
                    model=session.model,
                    temperature=session.temperature,
                )
            except Exception as exc:  # pragma: no cover - network failure
                error_msg = str(exc)
                logger.exception("Error al generar respuesta de OpenAI: %s", error_msg)
                # Provide more specific error messages for common issues
                if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                    raise APIException(
                        "Error de autenticación con OpenAI. Verifica la configuración de la API key."
                    ) from exc
                elif "rate limit" in error_msg.lower() or "quota" in error_msg.lower():
                    raise APIException(
                        "Límite de tasa excedido. Por favor, intenta de nuevo en unos momentos."
                    ) from exc
                elif "model" in error_msg.lower():
                    raise APIException(
                        f"Error con el modelo de OpenAI: {error_msg}"
                    ) from exc
                else:
                    raise APIException(
                        f"No fue posible generar la respuesta en este momento: {error_msg}"
                    ) from exc

            chunk_ids = [chunk.id for chunk in chunks]
            assistant_message = ChatMessage.objects.create(
                session=session,
                role=MessageRole.ASSISTANT,
                content=answer_text,
                chunk_ids=chunk_ids,
                metadata={"usage": usage},
            )

        response_payload = {
            "user_message": ChatMessageSerializer(user_message).data,
            "assistant_message": ChatMessageSerializer(assistant_message).data,
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)

