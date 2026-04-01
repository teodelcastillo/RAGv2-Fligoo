from __future__ import annotations

from django.db.models import Count, OuterRef, Prefetch, Subquery  # Count used in subquery helper
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.chat.models import ChatSession
from apps.chat.api.serializers import ChatSessionSerializer, ChatSessionCreateSerializer
from apps.document.models import Document
from apps.evaluation.api.serializers import EvaluationRunSerializer
from apps.evaluation.models import EvaluationRun, PillarEvaluationResult
from apps.project.api.permissions import ProjectAccessPermission
from apps.project.api.serializers import (
    ProjectDocumentAttachSerializer,
    ProjectSerializer,
    ProjectShareSerializer,
    ProjectShareWriteSerializer,
    ProjectWriteSerializer,
)
from apps.project.models import Project, ProjectDocument, ProjectShare


def _skill_execution_count_subquery():
    """
    Returns a Subquery that counts SkillExecutions for a given project.
    Defined as a function to keep the import lazy and avoid circular dependencies.
    """
    from apps.skill.models import SkillExecution
    return (
        SkillExecution.objects
        .filter(project=OuterRef("pk"))
        .values("project")
        .annotate(c=Count("id"))
        .values("c")[:1]
    )


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.none()
    permission_classes = [IsAuthenticated, ProjectAccessPermission]
    serializer_class = ProjectSerializer
    lookup_field = "slug"

    def get_queryset(self):
        user = self.request.user
        return (
            Project.objects.for_user(user)
            .select_related("owner")
            .prefetch_related(
                Prefetch(
                    "project_documents",
                    queryset=ProjectDocument.objects.select_related("document"),
                ),
                Prefetch(
                    "shares",
                    queryset=ProjectShare.objects.select_related("user"),
                ),
            )
            .annotate(
                skill_executions_count=Subquery(
                    _skill_execution_count_subquery()
                )
            )
            .distinct()
        )

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return ProjectWriteSerializer
        return ProjectSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        project = self.get_object()
        if not project.can_edit(self.request.user):
            raise PermissionDenied("No tienes permisos para editar este proyecto.")
        serializer.save()

    def perform_destroy(self, instance):
        if not instance.can_edit(self.request.user):
            raise PermissionDenied("No tienes permisos para eliminar este proyecto.")
        instance.delete()

    @action(
        detail=True,
        methods=["post"],
        url_path="documents",
        url_name="add-document",
    )
    def add_documents(self, request, slug=None):
        project = self.get_object()
        self._ensure_editor(project)
        serializer = ProjectDocumentAttachSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        for document in serializer.get_documents():
            ProjectDocument.objects.get_or_create(
                project=project,
                document=document,
                defaults={"added_by": request.user},
            )
        return Response(
            self._serialize_project(project),
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"documents/(?P<document_slug>[^/]+)",
        url_name="remove-document",
    )
    def remove_document(self, request, slug=None, document_slug=None):
        project = self.get_object()
        self._ensure_editor(project)
        document = get_object_or_404(Document, slug=document_slug)
        deleted, _ = ProjectDocument.objects.filter(
            project=project, document=document
        ).delete()
        if not deleted:
            return Response(
                {"detail": "Documento no encontrado en el proyecto."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="shares",
        url_name="shares",
    )
    def shares(self, request, slug=None):
        project = self.get_object()
        self._ensure_share_manager(project)
        if request.method == "GET":
            serializer = ProjectShareSerializer(
                project.shares.select_related("user"),
                many=True,
            )
            return Response(serializer.data)

        serializer = ProjectShareWriteSerializer(
            data=request.data,
            context={"project": project},
        )
        serializer.is_valid(raise_exception=True)
        share, _ = ProjectShare.objects.update_or_create(
            project=project,
            user=serializer.validated_data["user"],
            defaults={"role": serializer.validated_data["role"]},
        )
        output = ProjectShareSerializer(share)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"shares/(?P<share_id>[^/]+)",
        url_name="share-detail",
    )
    def manage_share(self, request, slug=None, share_id=None):
        project = self.get_object()
        self._ensure_share_manager(project)
        share = get_object_or_404(ProjectShare, project=project, pk=share_id)

        if request.method == "PATCH":
            serializer = ProjectShareWriteSerializer(
                data=request.data,
                context={"project": project},
            )
            serializer.is_valid(raise_exception=True)
            share.role = serializer.validated_data["role"]
            share.save(update_fields=["role"])
            return Response(ProjectShareSerializer(share).data)

        share.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["get"],
        url_path="skill-executions",
        url_name="skill-executions",
    )
    def skill_executions(self, request, slug=None):
        """List all skill executions for a project."""
        project = self.get_object()
        if not project.can_view(request.user):
            raise PermissionDenied("No tienes permisos para ver este proyecto.")
        from apps.skill.models import SkillExecution
        from apps.skill.api.serializers import SkillExecutionSerializer
        executions = (
            SkillExecution.objects.filter(project=project)
            .select_related("skill", "owner", "document")
            .order_by("-created_at")
        )
        serializer = SkillExecutionSerializer(executions, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get"],
        url_path="evaluation-runs",
        url_name="evaluation-runs",
    )
    def evaluation_runs(self, request, slug=None):
        """Listar todas las ejecuciones de evaluaciones de un proyecto"""
        project = self.get_object()
        
        # Verificar permisos de visualización del proyecto
        if not project.can_view(request.user):
            raise PermissionDenied("No tienes permisos para ver este proyecto.")
        
        # Obtener los runs del proyecto con sus relaciones
        runs = (
            EvaluationRun.objects.filter(project=project)
            .select_related("evaluation", "owner", "project")
            .prefetch_related(
                Prefetch(
                    "pillar_results",
                    queryset=PillarEvaluationResult.objects.prefetch_related("metric_results"),
                )
            )
            .order_by("-created_at")
        )
        
        serializer = EvaluationRunSerializer(runs, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="chat-sessions",
        url_name="chat-sessions",
    )
    def chat_sessions(self, request, slug=None):
        project = self.get_object()

        if request.method == "GET":
            qs = (
                ChatSession.objects
                .filter(owner=request.user, project=project)
                .prefetch_related("allowed_documents")
                .order_by("-updated_at")
            )
            serializer = ChatSessionSerializer(
                qs, many=True, context={"request": request},
            )
            return Response(serializer.data)

        create_serializer = ChatSessionCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        create_serializer.is_valid(raise_exception=True)
        validated = create_serializer.validated_data

        session = ChatSession.objects.create(
            owner=request.user,
            project=project,
            title=validated.get("title", f"Chat: {project.name}"),
            system_prompt=validated.get("system_prompt", ""),
            model=validated.get("model", ChatSession._meta.get_field("model").default),
            temperature=validated.get("temperature", 0.1),
            language=validated.get("language", "es"),
        )

        slugs = validated.get("document_slugs", [])
        if slugs:
            docs = Document.objects.filter(slug__in=slugs)
            session.allowed_documents.set(docs)

        output = ChatSessionSerializer(session, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    def _ensure_editor(self, project: Project):
        if not project.can_edit(self.request.user):
            raise PermissionDenied("No tienes permisos para modificar este proyecto.")

    def _ensure_share_manager(self, project: Project):
        if not project.can_manage_shares(self.request.user):
            raise PermissionDenied("No puedes administrar los permisos de este proyecto.")

    def _serialize_project(self, project: Project):
        refreshed = self.get_queryset().get(pk=project.pk)
        return ProjectSerializer(
            refreshed, context=self.get_serializer_context()
        ).data

