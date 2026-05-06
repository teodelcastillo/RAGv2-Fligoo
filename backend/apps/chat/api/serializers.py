from __future__ import annotations

import os
from typing import List

from rest_framework import serializers

from apps.chat.models import ChatSession, ChatMessage
from apps.document.services import accessible_documents_for
from apps.document.models import Document, SmartChunk

CHAT_MAX_DOCUMENTS_PER_SESSION = int(os.environ.get("CHAT_MAX_DOCUMENTS_PER_SESSION", "20"))


class ChatSessionSerializer(serializers.ModelSerializer):
    document_slugs = serializers.SerializerMethodField()
    primary_document_slug = serializers.SlugField(
        source="primary_document.slug",
        read_only=True,
        allow_null=True,
    )
    project_slug = serializers.SlugField(
        source="project.slug",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = ChatSession
        fields = (
            "id",
            "title",
            "system_prompt",
            "model",
            "temperature",
            "language",
            "is_active",
            "created_at",
            "updated_at",
            "document_slugs",
            "primary_document_slug",
            "project_slug",
        )

    def get_document_slugs(self, obj: ChatSession) -> List[str]:
        return list(obj.allowed_documents.values_list("slug", flat=True))


class ChatSessionCreateSerializer(serializers.ModelSerializer):
    document_slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = ChatSession
        fields = (
            "title",
            "system_prompt",
            "model",
            "temperature",
            "language",
            "document_slugs",
        )

    def validate_document_slugs(self, slugs: List[str]) -> List[str]:
        # Si la lista está vacía, es válido (sesión sin documentos)
        if not slugs:
            return slugs

        unique_slugs = list(dict.fromkeys(slugs))
        if len(unique_slugs) > CHAT_MAX_DOCUMENTS_PER_SESSION:
            raise serializers.ValidationError(
                "Demasiados documentos seleccionados para una sesión de chat: "
                f"{len(unique_slugs)} seleccionados, máximo "
                f"{CHAT_MAX_DOCUMENTS_PER_SESSION}. "
                "Reducí el alcance para mantener respuestas completas y predecibles."
            )
        
        user = self.context["request"].user
        available_docs = accessible_documents_for(user, unique_slugs)
        found_slugs = set(available_docs.values_list("slug", flat=True))
        missing = [slug for slug in unique_slugs if slug not in found_slugs]
        if missing:
            raise serializers.ValidationError(
                f"Documentos no encontrados o sin permisos: {', '.join(missing)}"
            )
        return unique_slugs

    def create(self, validated_data):
        slugs = validated_data.pop("document_slugs", [])
        session = ChatSession.objects.create(**validated_data)
        if slugs:
            docs = Document.objects.filter(slug__in=slugs)
            session.allowed_documents.set(docs)
        return session


class ChatMessageSerializer(serializers.ModelSerializer):
    chunks = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "session",
            "role",
            "content",
            "chunk_ids",
            "chunks",
            "metadata",
            "created_at",
        )
        read_only_fields = fields

    def get_chunks(self, obj: ChatMessage):
        if not obj.chunk_ids:
            return []
        chunks_by_id = {
            chunk.id: chunk
            for chunk in SmartChunk.objects.filter(id__in=obj.chunk_ids).select_related("document")
        }
        serialized = []
        for chunk_id in obj.chunk_ids:
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            serialized.append(
                {
                    "id": chunk.id,
                    "document_slug": chunk.document.slug,
                    "document_name": chunk.document.name,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                }
            )
        return serialized


class ChatMessageCreateSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=ChatSession.objects.all())
    content = serializers.CharField(allow_blank=False, max_length=4000)

    def validate_session(self, session: ChatSession):
        user = self.context["request"].user
        if not user.is_staff and session.owner_id != user.id:
            raise serializers.ValidationError("No tienes acceso a esta sesión.")
        if not session.is_active:
            raise serializers.ValidationError("La sesión está inactiva.")
        doc_count = session.allowed_documents.count()
        if doc_count > CHAT_MAX_DOCUMENTS_PER_SESSION:
            raise serializers.ValidationError(
                "Esta sesión tiene demasiados documentos para un chat predecible: "
                f"{doc_count} documentos, máximo {CHAT_MAX_DOCUMENTS_PER_SESSION}. "
                "Creá una sesión con menos documentos o aumentá "
                "CHAT_MAX_DOCUMENTS_PER_SESSION si el entorno lo soporta."
            )
        return session

