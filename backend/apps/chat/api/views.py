from __future__ import annotations

import logging

from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.chat.api.serializers import (
    ChatMessageCreateSerializer,
    ChatMessageSerializer,
    ChatSessionAddDocumentsSerializer,
    ChatSessionCreateSerializer,
    ChatSessionSerializer,
)
from apps.chat.models import ChatMessage, ChatSession, MessageRole
from apps.chat.services.agents import ChatAgentService, ANALYSIS_MODE_SIMPLE
from apps.document.models import Document
from rest_framework.decorators import action

logger = logging.getLogger(__name__)


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

    @action(
        detail=True,
        methods=["patch"],
        url_path="add-documents",
        url_name="add-documents",
    )
    def add_documents(self, request, pk=None):
        """
        Añade documentos a la sesión de chat.
        Los documentos se añaden a los ya existentes (no reemplazan).
        """
        session = self.get_object()
        
        # Verificar permisos
        if not request.user.is_staff and session.owner_id != request.user.id:
            return Response(
                {"detail": "No tienes permisos para modificar esta sesión."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = ChatSessionAddDocumentsSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        
        slugs = serializer.validated_data["document_slugs"]
        docs = Document.objects.filter(slug__in=slugs)
        
        # Añadir documentos (add() no duplica si ya existen)
        session.allowed_documents.add(*docs)
        
        output = ChatSessionSerializer(
            session, context=self.get_serializer_context()
        )
        return Response(output.data, status=status.HTTP_200_OK)


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

        analysis_mode = serializer.validated_data.get("analysis_mode") or ANALYSIS_MODE_SIMPLE

        agent = ChatAgentService(
            user=request.user,
            session=session,
            analysis_mode=analysis_mode,
            question=content,
        )
        user_message, assistant_message = agent.run()

        response_payload = {
            "user_message": ChatMessageSerializer(user_message).data,
            "assistant_message": ChatMessageSerializer(assistant_message).data,
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)

