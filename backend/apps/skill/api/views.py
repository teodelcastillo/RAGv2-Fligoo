from __future__ import annotations

from django.db.models import Prefetch, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.skill.api.serializers import (
    RunSkillSerializer,
    SkillExecutionSerializer,
    SkillSerializer,
    SkillWriteSerializer,
)
from apps.skill.models import ExecutionStatus, Skill, SkillExecution, SkillStep
from apps.skill.models import ExecutionOutputMode, SkillType
from apps.skill.tasks import run_skill_task


class SkillViewSet(viewsets.ModelViewSet):
    """
    CRUD for Skills + the run action.
    Returns: Ecofilia templates (owner=null) + the requesting user's own skills.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SkillSerializer
    lookup_field = "slug"

    def get_queryset(self):
        user = self.request.user
        qs = (
            Skill.objects
            .filter(Q(owner__isnull=True) | Q(owner=user))
            .prefetch_related(
                Prefetch("steps", queryset=SkillStep.objects.order_by("position"))
            )
            .select_related("owner")
        )
        skill_type = self.request.query_params.get("skill_type")
        if skill_type:
            qs = qs.filter(skill_type=skill_type)
        context = self.request.query_params.get("context")
        if context:
            # Match skills whose allowed_contexts includes this context OR "any"
            qs = qs.filter(
                Q(allowed_contexts__contains=[context]) |
                Q(allowed_contexts__contains=["any"])
            )
        context_slug = self.request.query_params.get("context_slug")
        if context == "repository" and context_slug:
            from apps.repository.models import Repository
            try:
                repository = Repository.objects.for_user(user).get(slug=context_slug)
            except Repository.DoesNotExist:
                return qs.none()
            qs = qs.filter(enabled_repositories=repository).distinct()
        elif context == "project" and context_slug:
            from apps.project.models import Project
            try:
                project = Project.objects.for_user(user).get(slug=context_slug)
            except Project.DoesNotExist:
                return qs.none()
            qs = qs.filter(enabled_projects=project).distinct()
        return qs

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return SkillWriteSerializer
        return SkillSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, is_template=False)

    def perform_update(self, serializer):
        skill = self.get_object()
        if not skill.can_edit(self.request.user):
            raise PermissionDenied("You cannot edit this skill.")
        serializer.save()

    def perform_destroy(self, instance):
        if not instance.can_edit(self.request.user):
            raise PermissionDenied("You cannot delete this skill.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="run")
    def run(self, request, slug=None):
        """
        Execute a skill against a context.
        QUICK skills run synchronously and return the full output immediately.
        COPILOT skills are dispatched asynchronously and return the execution ID.
        """
        skill = self.get_object()

        serializer = RunSkillSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Validate the requested context type is allowed by this skill
        context_type = data["context_type"]
        if "any" not in skill.allowed_contexts and context_type not in skill.allowed_contexts:
            return Response(
                {"detail": f"This skill does not support '{context_type}' context. "
                           f"Allowed: {skill.allowed_contexts}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not self._skill_enabled_for_context(skill, context_type, data):
            return Response(
                {"detail": "This skill is not enabled for this workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            skill.skill_type == SkillType.COPILOT
            and data.get("output_mode") == ExecutionOutputMode.TABLE
        ):
            return Response(
                {"detail": "Table output mode is currently supported only for Quick skills."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        execution = SkillExecution.objects.create(
            skill=skill,
            owner=request.user,
            repository=data.get("repository"),
            project=data.get("project"),
            document=data.get("document"),
            extra_instructions=data.get("extra_instructions", ""),
            output_mode=data.get("output_mode"),
            metadata={
                "table_columns": data.get("table_columns", []),
                "table_schema": data.get("table_schema", {}),
            },
            status=ExecutionStatus.PENDING,
        )

        if skill.skill_type == SkillType.QUICK:
            # Run synchronously — result is ready when this returns
            run_skill_task(execution.id)
            execution.refresh_from_db()
            return Response(
                SkillExecutionSerializer(execution).data,
                status=status.HTTP_200_OK,
            )
        else:
            # Dispatch async for multi-step copilot
            run_skill_task.delay(execution.id)
            return Response(
                SkillExecutionSerializer(execution).data,
                status=status.HTTP_202_ACCEPTED,
            )

    def _skill_enabled_for_context(self, skill: Skill, context_type: str, data: dict) -> bool:
        if context_type == "document":
            return True
        if context_type == "repository":
            repository = data.get("repository")
            return bool(repository and repository.enabled_skills.filter(pk=skill.pk).exists())
        if context_type == "project":
            project = data.get("project")
            return bool(project and project.enabled_skills.filter(pk=skill.pk).exists())
        return False


class SkillExecutionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Read-only view of skill executions for the current user.
    Supports filtering by skill, status, repository, project.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SkillExecutionSerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            SkillExecution.objects
            .filter(owner=user)
            .select_related("skill", "repository", "project", "document")
        )
        if skill_slug := self.request.query_params.get("skill"):
            qs = qs.filter(skill__slug=skill_slug)
        if repo_slug := self.request.query_params.get("repository"):
            qs = qs.filter(repository__slug=repo_slug)
        if project_slug := self.request.query_params.get("project"):
            qs = qs.filter(project__slug=project_slug)
        if status_filter := self.request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        return qs
