from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.document.models import SmartChunk, Document, DocumentShare, DocumentShareRole

User = get_user_model()

class SmartChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmartChunk
        fields = [
            'id',
            'content',
            'chunk_index',
            'document_id',
            'token_count',
            'embedding',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at', "content_norm"]


class DocumentCreateSerializer(serializers.ModelSerializer):
    file = serializers.FileField(required=True, allow_null=False, allow_empty_file=False)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    is_public = serializers.BooleanField(required=False, default=False)
    year = serializers.IntegerField(required=False, allow_null=True)
    region = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    topics = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        allow_null=True
    )
    source = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    
    class Meta:
        model = Document
        fields = [
            'file',
            'name',
            'category',
            'description',
            'is_public',
            'year',
            'region',
            'topics',
            'source',
        ]
    
    def validate_file(self, value):
        """Ensure the file is provided and not empty."""
        if not value:
            raise serializers.ValidationError("File is required.")
        return value
    
    def validate_is_public(self, value):
        """Only superusers can set is_public field"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            if value and not request.user.is_superuser:
                raise serializers.ValidationError(
                    "Only superadmins can set the is_public field."
                )
        return value


class DocumentBulkCreateSerializer(serializers.Serializer):
    """Serializer for bulk document upload - accepts multiple files"""
    files = serializers.ListField(
        child=serializers.FileField(required=True, allow_null=False, allow_empty_file=False),
        required=True,
        min_length=1,
        max_length=100,  # Limitar a 100 archivos por request para evitar sobrecarga
    )
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    is_public = serializers.BooleanField(required=False, default=False)
    year = serializers.IntegerField(required=False, allow_null=True)
    region = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    topics = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        allow_null=True
    )
    source = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255)
    
    def validate_files(self, value):
        """Validate that at least one file is provided and not empty."""
        if not value or len(value) == 0:
            raise serializers.ValidationError("At least one file is required.")
        
        # Validar que ningún archivo esté vacío
        for file in value:
            if not file:
                raise serializers.ValidationError("All files must be provided and not empty.")
            if file.size == 0:
                raise serializers.ValidationError("Files cannot be empty.")
        
        return value
    
    def validate_is_public(self, value):
        """Only superusers can set is_public field"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            if value and not request.user.is_superuser:
                raise serializers.ValidationError(
                    "Only superadmins can set the is_public field."
                )
        return value

class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for listing documents - read-only fields"""
    is_public = serializers.BooleanField(read_only=True)
    is_owner = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    
    class Meta:
        model = Document
        fields = [
            'id',
            'slug',
            'name',
            'category',
            'description',
            'file',
            'is_public',
            'is_owner',
            'owner_email',
            'created_at',
            'year',
            'region',
            'topics',
            'source',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'extracted_text',
            'chunking_status',
            'chunking_done',
            'chunking_offset',
            'last_error',
            'retry_count',
            'is_public',
            'owner',
            'name',
            'category',
            'description',
            'year',
            'region',
            'topics',
            'source',
        ]
    
    def get_is_owner(self, obj):
        """Indica si el usuario actual es el propietario del documento"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            return obj.owner == request.user
        return False


class DocumentDetailSerializer(serializers.ModelSerializer):
    """Serializer for retrieving a single document with all fields"""
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    
    class Meta:
        model = Document
        fields = [
            'id',
            'slug',
            'name',
            'category',
            'description',
            'file',
            'created_at',
            'chunking_status',
            'chunking_done',
            'is_public',
            'owner_email',
            'year',
            'region',
            'topics',
            'source',
        ]
        read_only_fields = [
            'id',
            'slug',
            'created_at',
            'chunking_status',
            'chunking_done',
            'owner_email',
        ]


class DocumentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating document metadata"""
    is_public = serializers.BooleanField(required=False)
    topics = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        allow_null=True
    )
    
    class Meta:
        model = Document
        fields = [
            'name',
            'category',
            'description',
            'is_public',
            'year',
            'region',
            'topics',
            'source',
        ]
    
    def validate_is_public(self, value):
        """Only superusers can modify is_public field"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            if not request.user.is_superuser:
                raise serializers.ValidationError(
                    "Only superadmins can modify the is_public field."
                )
        return value
    
    def update(self, instance, validated_data):
        """Update document, but restrict is_public to superusers"""
        request = self.context.get('request')
        
        # Remove is_public from validated_data if user is not superuser
        if request and hasattr(request, 'user'):
            if not request.user.is_superuser and 'is_public' in validated_data:
                validated_data.pop('is_public')
        
        return super().update(instance, validated_data)


class DocumentShareSerializer(serializers.ModelSerializer):
    """Serializer for reading document shares"""
    user_email = serializers.EmailField(source="user.email", read_only=True)
    
    class Meta:
        model = DocumentShare
        fields = ("id", "user", "user_email", "role", "created_at")
        read_only_fields = ("id", "user_email", "created_at")


class DocumentShareWriteSerializer(serializers.Serializer):
    """Serializer for creating/updating document shares"""
    user_email = serializers.EmailField()
    role = serializers.ChoiceField(choices=DocumentShareRole.choices)
    
    def validate(self, attrs):
        """Valida el email y obtiene el usuario"""
        email = attrs.get('user_email')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({
                'user_email': f"No existe un usuario con el email: {email}"
            })
        
        document = self.context.get("document")
        if document and document.owner == user:
            raise serializers.ValidationError({
                'user_email': "El propietario del documento no puede ser compartido."
            })
        
        # Reemplazar user_email con user para que la vista lo use
        attrs['user'] = user
        return attrs