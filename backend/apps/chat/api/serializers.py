from __future__ import annotations

from typing import List

from rest_framework import serializers

from apps.chat.models import ChatSession, ChatMessage
from apps.document.services import accessible_documents_for
from apps.document.models import Document, SmartChunk


class ChatSessionSerializer(serializers.ModelSerializer):
    document_slugs = serializers.SerializerMethodField()

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
        )

    def get_document_slugs(self, obj: ChatSession) -> List[str]:
        return list(obj.allowed_documents.values_list("slug", flat=True))


class ChatSessionCreateSerializer(serializers.ModelSerializer):
    document_slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=False,
        write_only=True,
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
        user = self.context["request"].user
        available_docs = accessible_documents_for(user, slugs)
        found_slugs = set(available_docs.values_list("slug", flat=True))
        missing = [slug for slug in slugs if slug not in found_slugs]
        if missing:
            raise serializers.ValidationError(
                f"Documentos no encontrados o sin permisos: {', '.join(missing)}"
            )
        return slugs

    def create(self, validated_data):
        slugs = validated_data.pop("document_slugs")
        session = ChatSession.objects.create(**validated_data)
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
        chunks = SmartChunk.objects.filter(id__in=obj.chunk_ids).select_related("document")
        serialized = []
        for chunk in chunks:
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
        return session

