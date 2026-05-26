from __future__ import annotations

from django.db.models import Count, OuterRef, Prefetch, Q, Subquery  # Count used in subquery helper
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.chat.models import ChatMessage, ChatSession, ChatSessionType, MessageRole
from apps.chat.api.serializers import (
    ChatMessageSerializer,
    ChatSessionSerializer,
    ChatSessionCreateSerializer,
)
from apps.chat.services.copilot import (
    generate_copilot_autocomplete,
    initialize_project_structure,
    process_copilot_message,
)
from apps.document.models import Document
from apps.evaluation.api.serializers import EvaluationRunSerializer
from apps.evaluation.models import EvaluationRun, PillarEvaluationResult
from apps.project.api.permissions import ProjectAccessPermission
from apps.project.api.serializers import (
    CopilotAutocompleteSerializer,
    CopilotMessageCreateSerializer,
    InitializeStructureSerializer,
    ProjectDocumentAttachSerializer,
    ProjectSectionCreateSerializer,
    ProjectSectionSerializer,
    ProjectSectionUpdateSerializer,
    ProjectSerializer,
    ProjectShareRoleUpdateSerializer,
    ProjectShareSerializer,
    ProjectShareWriteSerializer,
    ProjectWriteSerializer,
)
from apps.project.models import Project, ProjectDocument, ProjectSection, ProjectShare


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
            .select_related("owner", "blueprint_document", "structure_template")
            .prefetch_related(
                Prefetch(
                    "project_documents",
                    queryset=ProjectDocument.objects.select_related("document"),
                ),
                Prefetch(
                    "shares",
                    queryset=ProjectShare.objects.select_related("user"),
                ),
                "enabled_skills",
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
            serializer = ProjectShareRoleUpdateSerializer(data=request.data)
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
        """List skill executions for this project (shared collaborators see all runs)."""
        project = self.get_object()
        if not project.can_view(request.user):
            raise PermissionDenied("No tienes permisos para ver este proyecto.")
        from apps.skill.models import SkillExecution
        from apps.skill.api.serializers import SkillExecutionSerializer
        qs = (
            SkillExecution.objects.filter(project=project)
            .select_related("skill", "owner", "document")
        )
        executions = qs.order_by("-created_at")
        serializer = SkillExecutionSerializer(executions, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get"],
        url_path="evaluation-runs",
        url_name="evaluation-runs",
    )
    def evaluation_runs(self, request, slug=None):
        """Runs de evaluación en este proyecto (colaboradores con acceso ven todos)."""
        project = self.get_object()

        if not project.can_view(request.user):
            raise PermissionDenied("No tienes permisos para ver este proyecto.")

        qs = (
            EvaluationRun.objects.filter(project=project)
            .select_related("evaluation", "owner", "project")
            .prefetch_related(
                Prefetch(
                    "pillar_results",
                    queryset=PillarEvaluationResult.objects.prefetch_related("metric_results"),
                )
            )
        )
        runs = qs.order_by("-created_at")

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
                ChatSession.objects.filter(owner=request.user, project=project)
                .annotate(_ecofilia_msg_count=Count("messages"))
                .filter(_ecofilia_msg_count__gt=0)
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

    # ------------------------------------------------------------------
    # Structure endpoints
    # ------------------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="structure", url_name="structure")
    def structure(self, request, slug=None):
        project = self.get_object()
        sections = ProjectSection.objects.filter(project=project).order_by("position")
        serializer = ProjectSectionSerializer(sections, many=True)
        return Response({
            "template_slug": project.structure_template.slug if project.structure_template else None,
            "template_name": project.structure_template.name if project.structure_template else None,
            "sections": serializer.data,
        })

    @action(detail=True, methods=["put"], url_path="structure/initialize", url_name="structure-initialize")
    def structure_initialize(self, request, slug=None):
        project = self.get_object()
        self._ensure_editor(project)
        serializer = InitializeStructureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sections = initialize_project_structure(
                project, serializer.validated_data["template_slug"],
            )
        except Exception as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST,
            )
        output = ProjectSectionSerializer(sections, many=True)
        return Response(output.data, status=status.HTTP_200_OK)

    @action(
        detail=True, methods=["patch", "delete"],
        url_path=r"structure/sections/(?P<position>\d+)",
        url_name="structure-section-update",
    )
    def update_section(self, request, slug=None, position=None):
        project = self.get_object()
        self._ensure_editor(project)
        section = get_object_or_404(
            ProjectSection, project=project, position=int(position),
        )

        if request.method == "DELETE":
            removed_position = section.position
            section.delete()
            # Compact remaining positions so the next section becomes N.
            following = ProjectSection.objects.filter(
                project=project, position__gt=removed_position,
            ).order_by("position")
            for sec in following:
                sec.position -= 1
                sec.save(update_fields=["position"])
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = ProjectSectionUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        update_fields = []
        for field in ("title", "description", "status", "notes", "output_snapshot"):
            if field in data:
                setattr(section, field, data[field])
                update_fields.append(field)
        if update_fields:
            section.save(update_fields=update_fields)
        return Response(ProjectSectionSerializer(section).data)

    @action(
        detail=True, methods=["post"],
        url_path="structure/sections", url_name="structure-section-create",
    )
    def create_section(self, request, slug=None):
        project = self.get_object()
        self._ensure_editor(project)
        serializer = ProjectSectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        last_position = (
            ProjectSection.objects.filter(project=project)
            .order_by("-position").values_list("position", flat=True).first()
        )
        position = data.get("position") or ((last_position or 0) + 1)
        # Shift conflicting positions one by one (highest first) to keep the
        # (project, position) unique_together constraint satisfied at every step.
        conflicting = list(
            ProjectSection.objects.filter(
                project=project, position__gte=position,
            ).order_by("-position")
        )
        for sec in conflicting:
            sec.position += 1
            sec.save(update_fields=["position"])
        section = ProjectSection.objects.create(
            project=project,
            title=data["title"],
            description=data.get("description", ""),
            position=position,
        )
        return Response(
            ProjectSectionSerializer(section).data,
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------------
    # Copilot endpoints
    # ------------------------------------------------------------------

    @action(
        detail=True, methods=["get", "post"],
        url_path="copilot/sessions", url_name="copilot-sessions",
    )
    def copilot_sessions(self, request, slug=None):
        project = self.get_object()

        if request.method == "GET":
            qs = (
                ChatSession.objects.filter(
                    owner=request.user,
                    project=project,
                    session_type=ChatSessionType.COPILOT,
                )
                .prefetch_related("allowed_documents")
                .order_by("-updated_at")
            )
            serializer = ChatSessionSerializer(
                qs, many=True, context={"request": request},
            )
            return Response(serializer.data)

        doc_ids = (
            ProjectDocument.objects.filter(project=project)
            .values_list("document_id", flat=True)
        )
        docs = Document.objects.filter(id__in=doc_ids)

        session = ChatSession.objects.create(
            owner=request.user,
            project=project,
            session_type=ChatSessionType.COPILOT,
            title=f"Copilot: {project.name}",
            system_prompt="",
            model=ChatSession._meta.get_field("model").default,
            temperature=0.3,
            language="es",
        )
        session.allowed_documents.set(docs)

        output = ChatSessionSerializer(session, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True, methods=["post"],
        url_path="copilot/messages", url_name="copilot-messages",
    )
    def copilot_messages(self, request, slug=None):
        project = self.get_object()
        serializer = CopilotMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = serializer.validated_data["content"]

        session_id = request.data.get("session")
        if session_id:
            session = get_object_or_404(
                ChatSession,
                pk=session_id,
                owner=request.user,
                project=project,
                session_type=ChatSessionType.COPILOT,
            )
        else:
            session = (
                ChatSession.objects.filter(
                    owner=request.user,
                    project=project,
                    session_type=ChatSessionType.COPILOT,
                )
                .order_by("-updated_at")
                .first()
            )
            if session is None:
                return Response(
                    {"detail": "No copilot session found. Create one first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        user_message = ChatMessage.objects.create(
            session=session, role=MessageRole.USER, content=content,
        )

        try:
            answer_text, metadata, chunk_ids = process_copilot_message(
                session, content, request.user,
            )
        except Exception as exc:
            user_message.delete()
            return Response(
                {"detail": f"Copilot error: {exc}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        assistant_message = ChatMessage.objects.create(
            session=session,
            role=MessageRole.ASSISTANT,
            content=answer_text,
            chunk_ids=chunk_ids,
            metadata=metadata,
        )

        return Response(
            {
                "user_message": ChatMessageSerializer(user_message).data,
                "assistant_message": ChatMessageSerializer(assistant_message).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True, methods=["post"],
        url_path="copilot/autocomplete", url_name="copilot-autocomplete",
    )
    def copilot_autocomplete(self, request, slug=None):
        """
        Inline ghost-text suggestion for the project editor.

        The editor calls this on caret pause or via keyboard shortcut. The
        response is a short continuation text the frontend overlays as ghost
        text — Tab to accept, Esc to dismiss.
        """
        project = self.get_object()
        serializer = CopilotAutocompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        section = None
        position = data.get("section_position")
        if position:
            section = ProjectSection.objects.filter(
                project=project, position=position,
            ).first()

        try:
            completion, usage = generate_copilot_autocomplete(
                project,
                before=data.get("before", ""),
                after=data.get("after", ""),
                section=section,
                doc_title=data.get("doc_title") or None,
            )
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"Autocomplete error: {exc}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "completion": completion,
                "usage": usage,
            },
            status=status.HTTP_200_OK,
        )

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


class StructureTemplateViewSet(
    viewsets.ModelViewSet,
):
    """CRUD viewset for project structure templates."""

    permission_classes = [IsAuthenticated]
    lookup_field = "slug"

    def get_queryset(self):
        from apps.project.models import ProjectStructureTemplate
        qs = ProjectStructureTemplate.objects.prefetch_related("sections").annotate(
            section_count=Count("sections"),
        )
        user = self.request.user
        if user.is_staff:
            return qs
        return qs.filter(Q(owner=user) | Q(owner__isnull=True))

    def get_serializer_class(self):
        from apps.project.api.serializers import (
            ProjectStructureTemplateListSerializer,
            ProjectStructureTemplateSerializer,
            ProjectStructureTemplateWriteSerializer,
        )

        if self.action == "list":
            return ProjectStructureTemplateListSerializer
        if self.action in {"create", "update", "partial_update"}:
            return ProjectStructureTemplateWriteSerializer
        return ProjectStructureTemplateSerializer

    def perform_create(self, serializer):
        is_global = bool(serializer.validated_data.get("is_global", False))
        if is_global:
            if not self.request.user.is_staff:
                raise PermissionDenied("Solo usuarios staff pueden crear plantillas globales.")
            serializer.save(owner=None)
            return
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        is_global_target = bool(serializer.validated_data.get("is_global", instance.owner_id is None))
        if instance.owner_id is None:
            if not self.request.user.is_staff:
                raise PermissionDenied("Solo usuarios staff pueden editar plantillas globales.")
        else:
            if instance.owner_id != self.request.user.id and not self.request.user.is_staff:
                raise PermissionDenied("No puedes editar una plantilla que no te pertenece.")
        if is_global_target and not self.request.user.is_staff:
            raise PermissionDenied("Solo usuarios staff pueden convertir plantillas a globales.")
        if is_global_target:
            serializer.save(owner=None)
        elif instance.owner_id is None and not self.request.user.is_staff:
            raise PermissionDenied("Solo staff puede reasignar plantillas globales.")
        else:
            # Keep owner if already set; if global->local by staff, make owner current user.
            owner = instance.owner if instance.owner_id is not None else self.request.user
            serializer.save(owner=owner)

    def perform_destroy(self, instance):
        if instance.owner_id is None and not self.request.user.is_staff:
            raise PermissionDenied("Solo usuarios staff pueden eliminar plantillas globales.")
        if instance.owner_id is not None and instance.owner_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("No puedes eliminar una plantilla que no te pertenece.")
        instance.delete()

