from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.document.models import Document
from apps.document.services import accessible_documents_for
from apps.repository.models import Repository, RepositoryDocument, RepositoryType

User = get_user_model()


class RepositoryDocumentSerializer(serializers.ModelSerializer):
    slug = serializers.CharField(source="document.slug", read_only=True)
    name = serializers.CharField(source="document.name", read_only=True)
    category = serializers.CharField(source="document.category", read_only=True, allow_null=True)
    description = serializers.CharField(source="document.description", read_only=True)

    class Meta:
        model = RepositoryDocument
        fields = ("id", "slug", "name", "category", "description", "is_active", "added_at")
        read_only_fields = fields


class RepositorySerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True, allow_null=True)
    documents = RepositoryDocumentSerializer(
        source="repository_documents", many=True, read_only=True
    )
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = (
            "id",
            "slug",
            "name",
            "description",
            "repo_type",
            "category",
            "owner",
            "owner_email",
            "documents",
            "document_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "repo_type",
            "owner",
            "owner_email",
            "documents",
            "document_count",
            "created_at",
            "updated_at",
        )

    def get_document_count(self, obj) -> int:
        return obj.repository_documents.count()


class RepositoryWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repository
        fields = ("name", "description")

    def create(self, validated_data):
        validated_data["repo_type"] = RepositoryType.PRIVATE
        return Repository.objects.create(**validated_data)


class RepositoryDocumentAttachSerializer(serializers.Serializer):
    document_slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=False,
    )

    def validate_document_slugs(self, slugs):
        request = self.context["request"]
        docs = accessible_documents_for(request.user, slugs)
        found_slugs = set(docs.values_list("slug", flat=True))
        missing = [slug for slug in slugs if slug not in found_slugs]
        if missing:
            raise serializers.ValidationError(
                f"Documentos no encontrados o sin permisos: {', '.join(missing)}"
            )
        self.context["validated_documents"] = list(docs)
        return slugs

    def get_documents(self):
        return self.context.get("validated_documents", [])
