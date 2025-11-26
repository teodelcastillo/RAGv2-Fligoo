from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.document.models import Document
from apps.document.services import accessible_documents_for
from apps.project.models import (
    Project,
    ProjectDocument,
    ProjectShare,
    ProjectShareRole,
)

User = get_user_model()


class ProjectDocumentSerializer(serializers.ModelSerializer):
    slug = serializers.CharField(source="document.slug", read_only=True)
    name = serializers.CharField(source="document.name", read_only=True)
    category = serializers.CharField(
        source="document.category", read_only=True
    )
    description = serializers.CharField(
        source="document.description", read_only=True
    )

    class Meta:
        model = ProjectDocument
        fields = (
            "id",
            "slug",
            "name",
            "category",
            "description",
            "is_primary",
            "note",
            "created_at",
        )
        read_only_fields = fields


class ProjectSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    owner_email = serializers.EmailField(
        source="owner.email", read_only=True
    )
    documents = ProjectDocumentSerializer(
        source="project_documents", many=True, read_only=True
    )

    class Meta:
        model = Project
        fields = (
            "id",
            "slug",
            "name",
            "description",
            "is_active",
            "owner",
            "owner_email",
            "documents",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "owner",
            "owner_email",
            "documents",
            "created_at",
            "updated_at",
        )


class ProjectWriteSerializer(ProjectSerializer):
    document_slugs = serializers.ListField(
        child=serializers.SlugField(),
        allow_empty=True,
        required=False,
        write_only=True,
    )

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + ("document_slugs",)

    def validate_document_slugs(self, slugs):
        if not slugs:
            return []
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

    def create(self, validated_data):
        document_slugs = validated_data.pop("document_slugs", [])
        project = Project.objects.create(**validated_data)
        self._sync_documents(project, document_slugs)
        return project

    def update(self, instance, validated_data):
        document_slugs = validated_data.pop("document_slugs", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if document_slugs is not None:
            instance.project_documents.all().delete()
            self._sync_documents(instance, document_slugs)
        return instance

    def _sync_documents(self, project: Project, slugs):
        if not slugs:
            return
        documents = self.context.get("validated_documents")
        if documents is None:
            documents = list(
                Document.objects.filter(slug__in=slugs)
            )
        existing_slugs = set(
            project.project_documents.values_list(
                "document__slug", flat=True
            )
        )
        for doc in documents:
            if doc.slug in existing_slugs:
                continue
            ProjectDocument.objects.create(
                project=project,
                document=doc,
                added_by=project.owner,
            )


class ProjectDocumentAttachSerializer(serializers.Serializer):
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


class ProjectShareSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = ProjectShare
        fields = ("id", "user", "user_email", "role", "created_at")
        read_only_fields = ("id", "user_email", "created_at")


class ProjectShareWriteSerializer(serializers.Serializer):
    user_id = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
    )
    role = serializers.ChoiceField(choices=ProjectShareRole.choices)

    def validate_user(self, user):
        project = self.context["project"]
        if user == project.owner:
            raise serializers.ValidationError(
                "No puedes compartir el proyecto contigo mismo."
            )
        return user

