from __future__ import annotations

import os

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.document.models import Document
from apps.document.utils.llm import ROLE_BALANCED, resolve_model
from apps.project.models import Project

# Phase 2: resolves to OpenAI MODEL_COMPLETION by default, or the Claude
# "balanced" tier (Sonnet) when LLM_PROVIDER=anthropic. Only affects new
# sessions; existing sessions keep their stored model.
DEFAULT_CHAT_MODEL = resolve_model(ROLE_BALANCED)


class ChatSessionType(models.TextChoices):
    STANDARD = "standard", _("Standard")
    COPILOT = "copilot", _("Copilot")


class MessageRole(models.TextChoices):
    SYSTEM = "system", _("System")
    USER = "user", _("User")
    ASSISTANT = "assistant", _("Assistant")


class ChatSession(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="chat_sessions",
        on_delete=models.CASCADE,
    )
    primary_document = models.ForeignKey(
        Document,
        related_name="primary_chat_session",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Documento principal asociado a esta sesión de chat",
    )
    project = models.ForeignKey(
        Project,
        related_name="chat_sessions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Proyecto al que pertenece esta sesión de chat (si aplica)",
    )
    deliverable = models.ForeignKey(
        "project.ProjectDeliverable",
        related_name="chat_sessions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=(
            "Entregable activo al que pertenece esta sesión de copilot. "
            "Solo aplica a sesiones de copilot dentro de un proyecto."
        ),
    )
    repository = models.ForeignKey(
        "repository.Repository",
        related_name="chat_sessions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Repositorio al que pertenece esta sesión de chat (si aplica)",
    )
    session_type = models.CharField(
        max_length=20,
        choices=ChatSessionType.choices,
        default=ChatSessionType.STANDARD,
    )
    title = models.CharField(max_length=255)
    system_prompt = models.TextField(
        blank=True,
        default=(
            "Eres un asistente especializado en aprovechar el contexto entregado. "
            "Responde únicamente con la información disponible y menciona la fuente."
        ),
    )
    model = models.CharField(max_length=100, default=DEFAULT_CHAT_MODEL)
    temperature = models.FloatField(default=0.1)
    language = models.CharField(max_length=16, default="es")
    allowed_documents = models.ManyToManyField(
        Document,
        related_name="chat_sessions",
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("owner", "-updated_at"), name="chat_session_owner_upd_idx"),
            models.Index(fields=("primary_document",)),
            models.Index(fields=("project", "owner", "created_at")),
            models.Index(fields=("repository", "owner", "created_at")),
        ]
        constraints = [
            # Asegurar que solo haya una sesión primaria por documento y usuario
            models.UniqueConstraint(
                fields=["primary_document", "owner"],
                condition=models.Q(primary_document__isnull=False),
                name="unique_primary_document_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.owner})"


def touch_chat_session_activity(session_id: int) -> None:
    """Actualiza ``updated_at`` para que los listados ordenen por última actividad."""
    from django.utils import timezone

    ChatSession.objects.filter(pk=session_id).update(updated_at=timezone.now())


class ChatMessage(models.Model):
    session = models.ForeignKey(
        ChatSession,
        related_name="messages",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField()
    chunk_ids = ArrayField(
        base_field=models.IntegerField(),
        default=list,
        blank=True,
        help_text="IDs de SmartChunk utilizados para esta respuesta.",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=("session", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.session_id} - {self.role}"

