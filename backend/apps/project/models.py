from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.document.models import Document


class ProjectQuerySet(models.QuerySet):
    def for_user(self, user):
        if user.is_staff:
            return self
        return self.filter(Q(owner=user) | Q(shares__user=user)).distinct()


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="projects",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True, max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    documents = models.ManyToManyField(
        Document,
        through="ProjectDocument",
        related_name="projects",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.owner})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self) -> str:
        base = slugify(self.name) or "project"
        base = base[:255]
        slug = base
        counter = 1
        while Project.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            suffix = f"-{counter}"
            slug = f"{base[: 255 - len(suffix)]}{suffix}"
            counter += 1
        return slug

    def can_view(self, user) -> bool:
        if user.is_staff or self.owner_id == user.id:
            return True
        return self.shares.filter(user=user).exists()

    def can_edit(self, user) -> bool:
        if user.is_staff or self.owner_id == user.id:
            return True
        return self.shares.filter(
            user=user, role=ProjectShareRole.EDITOR
        ).exists()

    def can_manage_shares(self, user) -> bool:
        return user.is_staff or self.owner_id == user.id


class ProjectDocument(models.Model):
    project = models.ForeignKey(
        Project,
        related_name="project_documents",
        on_delete=models.CASCADE,
    )
    document = models.ForeignKey(
        Document,
        related_name="project_documents",
        on_delete=models.CASCADE,
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="added_project_documents",
        on_delete=models.SET_NULL,
    )
    is_primary = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "document")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.project_id}-{self.document_id}"


class ProjectShareRole(models.TextChoices):
    VIEWER = "viewer", _("Viewer")
    EDITOR = "editor", _("Editor")


class ProjectShare(models.Model):
    project = models.ForeignKey(
        Project,
        related_name="shares",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="project_shares",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        max_length=20,
        choices=ProjectShareRole.choices,
        default=ProjectShareRole.VIEWER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "user")
        ordering = ("project", "user")

    def __str__(self) -> str:
        return f"{self.project_id}-{self.user_id}-{self.role}"

