from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView, ListAPIView, RetrieveUpdateDestroyAPIView
from rest_framework import status, permissions
from rest_framework.response import Response

from django.db.models import Q

from apps.document.models import SmartChunk, Document
from apps.document.api.filters import DocumentFilter
from apps.document.api.serializers import (
    SmartChunkSerializer, 
    DocumentSerializer,
    DocumentCreateSerializer,
    DocumentDetailSerializer,
    DocumentUpdateSerializer
)


class RAGQueryView(APIView):
    def get(self, request):
        query_text = request.query_params.get("query")
        if not query_text:
            return Response({"error": "Missing query parameter"}, status=status.HTTP_400_BAD_REQUEST)

        
        user = request.user
        if user.is_staff:
            qs = SmartChunk.objects.all()
        else:
            qs = SmartChunk.objects.filter(
                Q(document__owner=user) | Q(document__is_public=True)
            )

        slugs = request.query_params.getlist("documents")
        if slugs:
            qs = qs.filter(document__slug__in=slugs)

        public_param = request.query_params.get("public")

        if public_param is not None:
            if public_param.lower() == "false":
                qs = qs.filter(document__is_public=False)
            elif public_param.lower() != "true":
                return Response({"error": "Invalid 'public' value. Use 'true' or 'false'."},
                                status=status.HTTP_400_BAD_REQUEST)

        try:
            chunks = qs.top_similar(query_text)
            serializer = SmartChunkSerializer(chunks, many=True)
            return Response({"query": query_text, "results": serializer.data})

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentCreateAPIView(CreateAPIView):
    queryset=Document.objects.all()
    serializer_class=DocumentCreateSerializer

    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save(owner=request.user)

        response_serializer = DocumentSerializer(document, context=self.get_serializer_context())
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
    

class DocumentListAPIView(ListAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    filterset_class = DocumentFilter
    
    def get_queryset(self):
        qs = Document.objects.all()
        user = self.request.user
        if not user.is_staff:
            qs = qs.filter(owner=user)

        return qs


class DocumentAccessPermission(permissions.BasePermission):
    """
    Permission class for document access:
    - Read: owner or staff users
    - Write/Delete: only owner or staff users
    """
    
    def has_object_permission(self, request, view, obj):
        # Staff users have full access
        if request.user.is_staff:
            return True
        
        # For safe methods (GET, HEAD, OPTIONS), allow if user is owner
        if request.method in permissions.SAFE_METHODS:
            return obj.owner == request.user
        
        # For write/delete methods, only owner can access
        return obj.owner == request.user


class DocumentDetailAPIView(RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a document instance.
    """
    queryset = Document.objects.all()
    permission_classes = [permissions.IsAuthenticated, DocumentAccessPermission]
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'
    
    def get_serializer_class(self):
        """Use different serializers for different operations"""
        if self.request.method == 'GET':
            return DocumentDetailSerializer
        elif self.request.method in ['PUT', 'PATCH']:
            return DocumentUpdateSerializer
        return DocumentSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions"""
        qs = Document.objects.all()
        user = self.request.user
        if not user.is_staff:
            qs = qs.filter(owner=user)
        return qs
    
    def perform_destroy(self, instance):
        """Delete the document instance"""
        instance.delete()