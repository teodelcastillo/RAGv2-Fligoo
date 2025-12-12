# apps/documents/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.document.api.views import (
    RAGQueryView, 
    DocumentCreateAPIView,
    DocumentListAPIView,
    DocumentViewSet,
)

router = DefaultRouter()
router.register(r'', DocumentViewSet, basename='document')

urlpatterns = [
    path("rag/", RAGQueryView.as_view(), name="rag-query"),
    path('create/', DocumentCreateAPIView.as_view(), name='documentcreate'),
    path('list/', DocumentListAPIView.as_view(), name='documentlist'),
    path('', include(router.urls)),
]
