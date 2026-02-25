from rest_framework.routers import DefaultRouter

from apps.evaluation.api.views_template import EvaluationTemplateViewSet

router = DefaultRouter()
router.register("", EvaluationTemplateViewSet, basename="evaluation-template")

urlpatterns = router.urls
