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
    class Meta:
        model = Document
        fields = [
            'file'
        ]

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