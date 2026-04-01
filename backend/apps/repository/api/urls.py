from rest_framework.routers import DefaultRouter

from apps.repository.api.views import RepositoryViewSet

router = DefaultRouter()
router.register("", RepositoryViewSet, basename="repository")

urlpatterns = router.urls
