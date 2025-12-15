# apps/documents/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.document.api.views import (
    RAGQueryView, 
    DocumentCreateAPIView,
    DocumentBulkCreateAPIView,
    DocumentListAPIView,
    DocumentViewSet,
    TopicsAutocompleteView,
)

router = DefaultRouter()
router.register(r'', DocumentViewSet, basename='document')

urlpatterns = [
    path("rag/", RAGQueryView.as_view(), name="rag-query"),
    path('create/', DocumentCreateAPIView.as_view(), name='documentcreate'),
    path('create/bulk/', DocumentBulkCreateAPIView.as_view(), name='documentbulkcreate'),
    path('list/', DocumentListAPIView.as_view(), name='documentlist'),
    path('topics/autocomplete/', TopicsAutocompleteView.as_view(), name='topics-autocomplete'),
    path('', include(router.urls)),
]
