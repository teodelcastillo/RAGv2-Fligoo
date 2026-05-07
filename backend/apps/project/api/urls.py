from rest_framework.routers import DefaultRouter

from apps.project.api.views import ProjectViewSet, StructureTemplateViewSet

router = DefaultRouter()
router.register("structure-templates", StructureTemplateViewSet, basename="structure-template")
router.register("", ProjectViewSet, basename="project")

urlpatterns = router.urls

