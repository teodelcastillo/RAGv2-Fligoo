from rest_framework import serializers
from apps.document.models import SmartChunk, Document

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
    
    class Meta:
        model = Document
        fields = [
            'file'
        ]
    
    def validate_file(self, value):
        """Ensure the file is provided and not empty."""
        if not value:
            raise serializers.ValidationError("File is required.")
        return value

class DocumentSerializer(serializers.ModelSerializer):
    """Serializer for listing documents - read-only fields"""
    class Meta:
        model = Document
        fields = [
            'slug',
            'name',
            'category',
            'description',
            'file'
        ]
        read_only_fields = [
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
        ]


class DocumentDetailSerializer(serializers.ModelSerializer):
    """Serializer for retrieving a single document with all fields"""
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    
    class Meta:
        model = Document
        fields = [
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
        ]
        read_only_fields = [
            'slug',
            'created_at',
            'chunking_status',
            'chunking_done',
            'owner_email',
        ]


class DocumentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating document metadata"""
    is_public = serializers.BooleanField(required=False)
    
    class Meta:
        model = Document
        fields = [
            'name',
            'category',
            'description',
            'is_public',
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