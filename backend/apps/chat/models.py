from __future__ import annotations

import os

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.document.models import Document

DEFAULT_CHAT_MODEL = os.environ.get("MODEL_COMPLETION", "gpt-4o-mini")


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
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.owner})"


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

