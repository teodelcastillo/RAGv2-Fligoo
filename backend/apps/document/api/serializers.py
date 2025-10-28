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