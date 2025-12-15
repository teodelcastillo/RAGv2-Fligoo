from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework import viewsets, mixins
from django.shortcuts import get_object_or_404

from django.db.models import Q

from apps.document.models import SmartChunk, Document, DocumentShare
from apps.document.api.filters import DocumentFilter
from apps.document.api.serializers import (
    SmartChunkSerializer, 
    DocumentSerializer,
    DocumentCreateSerializer,
    DocumentBulkCreateSerializer,
    DocumentDetailSerializer,
    DocumentUpdateSerializer,
    DocumentShareSerializer,
    DocumentShareWriteSerializer,
)
from apps.chat.models import ChatSession
from apps.chat.api.serializers import ChatSessionSerializer


class RAGQueryView(APIView):
    def get(self, request):
        query_text = request.query_params.get("query")
        if not query_text:
            return Response({"error": "Missing query parameter"}, status=status.HTTP_400_BAD_REQUEST)

        
        user = request.user
        if user.is_staff:
            qs = SmartChunk.objects.all()
        else:
            # Incluir chunks de documentos propios, públicos, compartidos y de proyectos compartidos
            from apps.project.models import ProjectShare
            shared_project_ids = ProjectShare.objects.filter(
                user=user
            ).values_list('project_id', flat=True)
            qs = SmartChunk.objects.filter(
                Q(document__owner=user) 
                | Q(document__is_public=True) 
                | Q(document__shares__user=user)
                | Q(document__projects__id__in=shared_project_ids)
            ).distinct()

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


class DocumentBulkCreateAPIView(APIView):
    """
    API View for bulk document upload.
    Accepts multiple files and creates a document for each one.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, *args, **kwargs):
        """
        Create multiple documents from multiple files.
        
        Expected format: multipart/form-data with multiple 'files' fields
        Example: files[]=file1.pdf&files[]=file2.pdf
        Also accepts: name, category, description, is_public (applied to all documents)
        """
        # Handle both 'files' as a list and 'files[]' format
        files = request.FILES.getlist('files') or request.FILES.getlist('files[]')
        
        if not files:
            return Response(
                {"error": "No files provided. Use 'files' or 'files[]' field(s)."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Prepare data for serializer validation
        data = {'files': files}
        
        # Add optional properties if provided
        if 'name' in request.data:
            data['name'] = request.data['name']
        if 'category' in request.data:
            data['category'] = request.data['category']
        if 'description' in request.data:
            data['description'] = request.data['description']
        if 'is_public' in request.data:
            data['is_public'] = request.data['is_public']
        
        # Validate using serializer
        serializer = DocumentBulkCreateSerializer(
            data=data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        validated_files = validated_data['files']
        
        # Extract properties to apply to all documents
        document_props = {}
        if 'name' in validated_data:
            document_props['name'] = validated_data['name']
        if 'category' in validated_data:
            document_props['category'] = validated_data['category']
        if 'description' in validated_data:
            document_props['description'] = validated_data['description']
        if 'is_public' in validated_data:
            document_props['is_public'] = validated_data['is_public']
        
        created_documents = []
        errors = []
        
        # Create a document for each file
        for index, file in enumerate(validated_files):
            try:
                # Create document with user-provided properties
                document = Document.objects.create(
                    owner=request.user,
                    file=file,
                    **document_props
                )
                created_documents.append(document)
            except Exception as e:
                errors.append({
                    'file_index': index,
                    'filename': file.name if hasattr(file, 'name') else 'unknown',
                    'error': str(e)
                })
        
        # Serialize created documents
        response_serializer = DocumentSerializer(
            created_documents,
            many=True,
            context=self.get_serializer_context()
        )
        
        response_data = {
            'created': len(created_documents),
            'failed': len(errors),
            'documents': response_serializer.data
        }
        
        if errors:
            response_data['errors'] = errors
        
        # Return 201 if all succeeded, 207 (Multi-Status) if some failed, 400 if all failed
        if len(errors) == 0:
            return Response(response_data, status=status.HTTP_201_CREATED)
        elif len(created_documents) > 0:
            return Response(response_data, status=status.HTTP_207_MULTI_STATUS)
        else:
            return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
    

class DocumentListAPIView(ListAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    filterset_class = DocumentFilter
    
    def get_queryset(self):
        qs = Document.objects.all()
        user = self.request.user
        scope = self.request.query_params.get('scope', 'all')  # 'all', 'own', 'public', 'shared'
        
        if user.is_staff:
            # Staff puede ver todos, pero puede filtrar por scope
            if scope == 'own':
                qs = qs.filter(owner=user)
            elif scope == 'public':
                qs = qs.filter(is_public=True)
            elif scope == 'shared':
                # Documentos compartidos con el usuario (excluyendo los propios)
                qs = qs.filter(shares__user=user).exclude(owner=user).distinct()
            # Si scope == 'all', no filtrar (ver todos)
        else:
            # Usuarios no-staff: pueden ver sus propios documentos, los públicos y los compartidos
            if scope == 'own':
                qs = qs.filter(owner=user)
            elif scope == 'public':
                qs = qs.filter(is_public=True)
            elif scope == 'shared':
                # Documentos compartidos con el usuario (excluyendo los propios)
                qs = qs.filter(shares__user=user).exclude(owner=user).distinct()
            else:  # scope == 'all'
                # Incluir documentos propios, públicos, compartidos y de proyectos compartidos
                from apps.project.models import ProjectShare
                shared_project_ids = ProjectShare.objects.filter(
                    user=user
                ).values_list('project_id', flat=True)
                qs = qs.filter(
                    Q(owner=user) 
                    | Q(is_public=True) 
                    | Q(shares__user=user)
                    | Q(projects__id__in=shared_project_ids)
                ).distinct()

        return qs


class DocumentAccessPermission(permissions.BasePermission):
    """
    Permission class for document access:
    - Read: owner, staff users, public documents, shared documents, or documents in shared projects
    - Write/Delete: owner, staff, or editor role in share (for public docs, only superuser)
    """
    
    def has_object_permission(self, request, view, obj):
        # Staff users have full access
        if request.user.is_staff:
            return True
        
        # For safe methods (GET, HEAD, OPTIONS)
        if request.method in permissions.SAFE_METHODS:
            return obj.can_view(request.user)
        
        # For write/delete methods
        # - If document is public, only superuser can modify/delete
        if obj.is_public:
            return request.user.is_superuser
        
        # Owner can always modify/delete
        if obj.owner == request.user:
            return True
        
        # Check if user has editor role in share
        return obj.can_edit(request.user)


class DocumentViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for retrieving, updating, and deleting document instances.
    Also handles sharing functionality.
    """
    queryset = Document.objects.all()
    permission_classes = [permissions.IsAuthenticated, DocumentAccessPermission]
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'
    
    def get_serializer_class(self):
        """Use different serializers for different operations"""
        if self.action == 'retrieve':
            return DocumentDetailSerializer
        elif self.action in ['update', 'partial_update']:
            return DocumentUpdateSerializer
        return DocumentSerializer
    
    def get_queryset(self):
        """Filter queryset based on user permissions"""
        qs = Document.objects.all()
        user = self.request.user
        if not user.is_staff:
            # Incluir documentos propios, públicos, compartidos y de proyectos compartidos
            from apps.project.models import ProjectShare
            shared_project_ids = ProjectShare.objects.filter(
                user=user
            ).values_list('project_id', flat=True)
            qs = qs.filter(
                Q(owner=user) 
                | Q(is_public=True) 
                | Q(shares__user=user)
                | Q(projects__id__in=shared_project_ids)
            ).distinct()
        return qs
    
    def perform_destroy(self, instance):
        """Delete the document instance"""
        instance.delete()
    
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="shares",
        url_name="shares",
    )
    def shares(self, request, slug=None):
        """List or create document shares"""
        document = self.get_object()
        if not document.can_manage_shares(request.user):
            raise PermissionDenied("No puedes administrar los permisos de este documento.")
        
        if request.method == "GET":
            serializer = DocumentShareSerializer(
                document.shares.select_related("user"),
                many=True,
            )
            return Response(serializer.data)
        
        serializer = DocumentShareWriteSerializer(
            data=request.data,
            context={"document": document, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        share, created = DocumentShare.objects.update_or_create(
            document=document,
            user=serializer.validated_data["user"],
            defaults={"role": serializer.validated_data["role"]},
        )
        output = DocumentShareSerializer(share)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(output.data, status=status_code)
    
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"shares/(?P<share_id>[^/]+)",
        url_name="share-detail",
    )
    def manage_share(self, request, slug=None, share_id=None):
        """Update or delete a document share"""
        document = self.get_object()
        if not document.can_manage_shares(request.user):
            raise PermissionDenied("No puedes administrar los permisos de este documento.")
        
        share = get_object_or_404(DocumentShare, document=document, pk=share_id)
        
        if request.method == "PATCH":
            serializer = DocumentShareWriteSerializer(
                data=request.data,
                context={"document": document, "request": request},
            )
            serializer.is_valid(raise_exception=True)
            share.role = serializer.validated_data["role"]
            share.save(update_fields=["role"])
            return Response(DocumentShareSerializer(share).data)
        
        share.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="chat-session",
        url_name="chat-session",
    )
    def chat_session(self, request, slug=None):
        """
        Obtener o crear la sesión de chat asociada a este documento.
        GET: Retorna la sesión existente o 404 si no existe
        POST: Crea una nueva sesión si no existe, o retorna la existente
        """
        document = self.get_object()
        
        # Verificar permisos de visualización
        if not document.can_view(request.user):
            raise PermissionDenied("No tienes permisos para ver este documento.")
        
        # Buscar sesión existente
        session = ChatSession.objects.filter(
            primary_document=document,
            owner=request.user
        ).first()
        
        if request.method == "GET":
            if session:
                serializer = ChatSessionSerializer(
                    session,
                    context={"request": request}
                )
                return Response(serializer.data)
            return Response(
                {"detail": "No hay sesión de chat para este documento."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # POST: Crear sesión si no existe
        if session:
            serializer = ChatSessionSerializer(
                session,
                context={"request": request}
            )
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        # Crear nueva sesión
        session = ChatSession.objects.create(
            owner=request.user,
            primary_document=document,
            title=f"Chat: {document.name}",
        )
        # Asociar el documento a allowed_documents también
        session.allowed_documents.add(document)
        
        serializer = ChatSessionSerializer(
            session,
            context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)