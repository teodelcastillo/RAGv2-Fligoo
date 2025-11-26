from rest_framework.routers import DefaultRouter

from apps.project.api.views import ProjectViewSet

router = DefaultRouter()
router.register("", ProjectViewSet, basename="project")

urlpatterns = router.urls

