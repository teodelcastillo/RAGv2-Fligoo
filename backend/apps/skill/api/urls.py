from rest_framework.routers import DefaultRouter

from apps.skill.api.views import SkillExecutionViewSet, SkillViewSet

router = DefaultRouter()
router.register("executions", SkillExecutionViewSet, basename="skill-execution")
router.register("", SkillViewSet, basename="skill")

urlpatterns = router.urls
