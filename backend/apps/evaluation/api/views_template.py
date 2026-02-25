"""API views for template-based evaluation dashboards."""

from django.db.models import Prefetch
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.evaluation.api.serializers_template import (
    EvaluationTemplateSerializer,
    RunEvaluationCreateSerializer,
    TemplateEvaluationRunSerializer,
)
from apps.evaluation.models_template import (
    EvaluationTemplate,
    TemplateEvaluationRun,
    TemplateEvaluationRunScore,
)
from apps.evaluation.services_asg import run_asg_evaluation
from apps.project.models import Project


class EvaluationTemplateViewSet(ReadOnlyModelViewSet):
    """GET /api/evaluation-templates/ - List evaluation templates with pillars and KPIs."""

    queryset = EvaluationTemplate.objects.prefetch_related("pillars__kpis")
    serializer_class = EvaluationTemplateSerializer
    permission_classes = [IsAuthenticated]


class RunEvaluationView(APIView):
    """POST /api/evaluations/run/ - Execute ASG evaluation on a project."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RunEvaluationCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        project = Project.objects.get(pk=serializer.validated_data["project_id"])
        template = EvaluationTemplate.objects.get(pk=serializer.validated_data["template_id"])

        if not project.can_edit(request.user):
            return Response(
                {"detail": "No tienes permisos para ejecutar evaluaciones en este proyecto."},
                status=status.HTTP_403_FORBIDDEN,
            )

        run = run_asg_evaluation(
            project=project,
            template=template,
            user=request.user,
        )
        # Optionally run async via Celery for long evaluations
        # run_asg_evaluation_task.delay(project.id, str(template.id), request.user.id)

        run = (
            TemplateEvaluationRun.objects.filter(pk=run.pk)
            .select_related("project", "template")
            .prefetch_related("scores__kpi__pillar")
            .first()
        )
        output = TemplateEvaluationRunSerializer(run)
        return Response(output.data, status=status.HTTP_201_CREATED)


class TemplateEvaluationRunViewSet(ReadOnlyModelViewSet):
    """GET /api/evaluations/ - List template evaluation runs with filters."""

    permission_classes = [IsAuthenticated]
    serializer_class = TemplateEvaluationRunSerializer

    def get_queryset(self):
        user = self.request.user
        project_ids = Project.objects.for_user(user).values_list("id", flat=True)
        qs = TemplateEvaluationRun.objects.filter(project_id__in=project_ids)

        project_id = self.request.query_params.get("projectId")
        if project_id:
            qs = qs.filter(project_id=project_id)
        template_id = self.request.query_params.get("templateId")
        if template_id:
            qs = qs.filter(template_id=template_id)
        run_id = self.request.query_params.get("runId")
        if run_id:
            qs = qs.filter(pk=run_id)

        return (
            qs.select_related("project", "template")
            .prefetch_related(
                Prefetch(
                    "scores",
                    queryset=TemplateEvaluationRunScore.objects.select_related("kpi__pillar"),
                )
            )
            .order_by("-executed_at")
        )
