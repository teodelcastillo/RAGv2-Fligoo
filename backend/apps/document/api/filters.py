import django_filters
from apps.document.models import Document

class DocumentFilter(django_filters.FilterSet):
    class Meta:
        model = Document
        fields = {
            'slug': ['exact', 'icontains'],
            'name': ['exact', 'icontains'],
            'extracted_text': ['icontains'],
            'category': ['exact', 'icontains'],
            'chunking_status': ['exact'],
            'created_at': ['exact', 'year__gt', 'year__lt'],
            'is_public': ['exact'],
        }
