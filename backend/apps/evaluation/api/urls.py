from rest_framework.routers import DefaultRouter

from apps.evaluation.api.views import EvaluationViewSet

router = DefaultRouter()
router.register("", EvaluationViewSet, basename="evaluation")

urlpatterns = router.urls

