from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.evaluation.api.views import EvaluationViewSet
from apps.evaluation.api.views_template import (
    EvaluationTemplateViewSet,
    RunEvaluationView,
    TemplateEvaluationRunViewSet,
)

router = DefaultRouter()
router.register("", EvaluationViewSet, basename="evaluation")

runs_router = DefaultRouter()
runs_router.register("", TemplateEvaluationRunViewSet, basename="evaluation-run")

urlpatterns = [
    path("run/", RunEvaluationView.as_view(), name="evaluation-run"),
    path("runs/", include(runs_router.urls)),
] + router.urls

