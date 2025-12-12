from rest_framework.routers import DefaultRouter

from apps.chat.api.views import ChatMessageViewSet, ChatSessionViewSet

router = DefaultRouter()
router.register(r"sessions", ChatSessionViewSet, basename="chat-session")
router.register(r"messages", ChatMessageViewSet, basename="chat-message")

urlpatterns = router.urls












