import uuid
from django.db import models
from django.db.models import QuerySet
from django.utils.text import slugify
from django.db.models import Func, F, TextField, GeneratedField, Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from pgvector.django import VectorField, CosineDistance
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth import get_user_model
from apps.document.utils.client_openia import embed_text
import os
import re
User = get_user_model()

class ChunkingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    DONE = "done", "Done"
    ERROR = "error", "Error"


class Document(models.Model):
    owner = models.ForeignKey(User, related_name="document_owner", on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True)
    slug = models.SlugField(unique=True, blank=True)
    category =  models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to='documents/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    extracted_text = models.TextField(blank=True)
    chunking_status = models.CharField(
        max_length=20,
        choices=ChunkingStatus.choices,
        default=ChunkingStatus.PENDING,
    )
    chunking_offset = models.IntegerField(default=0)
    chunking_done = models.BooleanField(default=False)
    last_error = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    is_public = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Si no hay name ni slug, generar ambos desde el nombre del archivo
        if not self.name and not self.slug:
            name = os.path.basename(self.file.name)
            name = os.path.splitext(name)[0] 
            self.name = name[:255]
            base_slug = slugify(name[:50])
            slug = base_slug
            counter = 1
            while Document.objects.filter(slug=slug).exists():
                s_counter = str(counter)
                slug = base_slug[:49-len(s_counter)]
                slug = f"{base_slug}-"+ s_counter
                counter += 1
            self.slug = slug
        # Si hay name pero no slug, generar slug desde el name proporcionado
        elif self.name and not self.slug:
            base_slug = slugify(self.name[:50])
            slug = base_slug
            counter = 1
            while Document.objects.filter(slug=slug).exists():
                s_counter = str(counter)
                slug = base_slug[:49-len(s_counter)]
                slug = f"{base_slug}-"+ s_counter
                counter += 1
            self.slug = slug
        # Si hay slug pero no name, y hay archivo, generar name desde el archivo
        elif self.slug and not self.name and self.file:
            name = os.path.basename(self.file.name)
            name = os.path.splitext(name)[0] 
            self.name = name[:255]

        super().save(*args, **kwargs)

    def can_view(self, user) -> bool:
        """Verifica si el usuario puede ver el documento"""
        if user.is_staff or self.owner_id == user.id:
            return True
        if self.is_public:
            return True
        return self.shares.filter(user=user).exists()

    def can_edit(self, user) -> bool:
        """Verifica si el usuario puede editar el documento"""
        if user.is_staff or self.owner_id == user.id:
            return True
        return self.shares.filter(
            user=user, role=DocumentShareRole.EDITOR
        ).exists()

    def can_manage_shares(self, user) -> bool:
        """Verifica si el usuario puede gestionar los shares del documento"""
        return user.is_staff or self.owner_id == user.id

    def __str__(self):
        return f'{self.id}-{self.name}'

class SmartChunkQuerySet(QuerySet):
    def top_similar(self, text: str, top_n=5):
        if not text:
            return self.none()

        query_embedding = embed_text(text)
        if not query_embedding:
            return self.none()
        numbers = [num for num in re.findall(r"\d+\.?\d*", text)]
        qs = self.annotate(
            distance=CosineDistance("embedding", query_embedding)
        )
        if numbers:
            q = Q()
            for num in numbers:
                q |= Q(content_norm__icontains=num)
            candidates = self.filter(q).only("id")[:1000]
            qs = qs.filter(id__in=candidates)

        return qs.order_by("distance")[:top_n]


    def top_similar2(self, text: str, top_n=5):
        if not text:
            return self.none()

        query_embedding = embed_text(text)
        if not query_embedding:
            return self.none()

        return self.annotate(
            distance=CosineDistance("embedding", query_embedding)
        ).order_by("distance")[:top_n]

class SmartChunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField()
    content = models.TextField()
    content_norm = GeneratedField(
        expression=Func(Lower(F("content")), function="immutable_unaccent"),
        output_field=TextField(),
        db_persist=True,     # matches STORED
        editable=False
    )
    token_count = models.IntegerField()
    title = models.CharField(max_length=255, blank=True, null=True)
    summary = models.TextField(blank=True)
    keywords = ArrayField(models.TextField(), blank=True, default=list)
    embedding = VectorField(dimensions=1536, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)



    class SmartChunkManager(models.Manager):
        def get_queryset(self):
            return SmartChunkQuerySet(self.model, using=self._db)

        # Optional shortcut to call on manager directly
        def top_similar(self, *args, **kwargs):
            return self.get_queryset().top_similar(*args, **kwargs)

    # class SmartChunkManager(models.Manager):
    #     #  def get_queryset(self):
    #     #     return super().get_queryset()
         
    #      def get_queryset(self, text, top_n=5):
    #         qs = self.get_queryset()
    #         if not text:<
    #             return qs.none()
    #         query_embedding = embed_text(text)
    #         if not query_embedding:
    #             return qs.none()
    #         return qs.annotate(
    #             distance=CosineDistance("embedding", query_embedding)
    #         ).order_by("distance")[:top_n]

    objects = SmartChunkManager()
    def __str__(self):
        return f"{self.id}-{self.document.name}"


class DocumentShareRole(models.TextChoices):
    VIEWER = "viewer", _("Viewer")
    EDITOR = "editor", _("Editor")


class DocumentShare(models.Model):
    document = models.ForeignKey(
        Document,
        related_name="shares",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        related_name="document_shares",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        max_length=20,
        choices=DocumentShareRole.choices,
        default=DocumentShareRole.VIEWER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("document", "user")
        ordering = ("document", "user")

    def __str__(self):
        return f"{self.document_id}-{self.user_id}-{self.role}"
