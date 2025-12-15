from __future__ import annotations

from typing import List

from rest_framework import serializers

from apps.chat.models import ChatSession, ChatMessage
from apps.document.services import accessible_documents_for
from apps.document.models import Document, SmartChunk


class ChatSessionSerializer(serializers.ModelSerializer):
    document_slugs = serializers.SerializerMethodField()
    primary_document_slug = serializers.SlugField(
        source="primary_document.slug",
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
        slugs = validated_data.pop("document_slugs", [])
        session = ChatSession.objects.create(**validated_data)
        if slugs:
            docs = Document.objects.filter(slug__in=slugs)
            session.allowed_documents.set(docs)
        return session


class ChatMessageSerializer(serializers.ModelSerializer):
    chunks = serializers.SerializerMethodField()
    recommended_documents = serializers.SerializerMethodField()

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
            "recommended_documents",
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

    def get_recommended_documents(self, obj: ChatMessage) -> List[dict]:
        """
        Retorna los documentos recomendados desde metadata.
        Facilita el acceso desde el frontend sin tener que parsear metadata manualmente.
        """
        if not obj.metadata:
            return []
        return obj.metadata.get("recommended_documents", [])


class ChatSessionAddDocumentsSerializer(serializers.Serializer):
    document_slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=False,
        required=True,
        help_text="Lista de slugs de documentos a añadir a la sesión",
    )

    def validate_document_slugs(self, slugs: List[str]) -> List[str]:
        if not slugs:
            raise serializers.ValidationError("Debes proporcionar al menos un documento.")
        
        user = self.context["request"].user
        available_docs = accessible_documents_for(user, slugs)
        found_slugs = set(available_docs.values_list("slug", flat=True))
        missing = [slug for slug in slugs if slug not in found_slugs]
        if missing:
            raise serializers.ValidationError(
                f"Documentos no encontrados o sin permisos: {', '.join(missing)}"
            )
        return slugs


class ChatMessageCreateSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=ChatSession.objects.all())
    content = serializers.CharField(allow_blank=False, max_length=4000)
    analysis_mode = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Modo de análisis opcional para activar el agente multi-step. "
            "Valores soportados: 'simple' (por defecto), "
            "'regulatory_compliance', 'esg_financial_analysis'."
        ),
    )

    def validate_session(self, session: ChatSession):
        user = self.context["request"].user
        if not user.is_staff and session.owner_id != user.id:
            raise serializers.ValidationError("No tienes acceso a esta sesión.")
        if not session.is_active:
            raise serializers.ValidationError("La sesión está inactiva.")
        return session

    def validate_analysis_mode(self, value: str) -> str:
        if not value:
            return ""

        allowed = {"simple", "regulatory_compliance", "esg_financial_analysis"}
        if value not in allowed:
            raise serializers.ValidationError(
                f"analysis_mode inválido. Usa uno de: {', '.join(sorted(allowed))}."
            )
        return value

