from __future__ import annotations

import os
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

DEFAULT_MODEL = os.environ.get("MODEL_COMPLETION", "gpt-4o-mini")


class SkillType(models.TextChoices):
    QUICK = "quick", _("Quick")
    COPILOT = "copilot", _("Copilot")


class SkillContext(models.TextChoices):
    REPOSITORY = "repository", _("Repository")
    PROJECT = "project", _("Project")
    DOCUMENT = "document", _("Document")
    ANY = "any", _("Any")


class ExecutionStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    RUNNING = "running", _("Running")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


# ---------------------------------------------------------------------------
# Skill definition
# ---------------------------------------------------------------------------

class Skill(models.Model):
    """
    A reusable AI automation template.

    owner=None means it's an Ecofilia-provided template visible to all users.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="skills",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    skill_type = models.CharField(
        max_length=20, choices=SkillType.choices, default=SkillType.QUICK
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True, max_length=255)
    description = models.TextField(blank=True)

    # Contexts where this skill can be executed
    allowed_contexts = models.JSONField(
        default=list,
        help_text='List of allowed contexts, e.g. ["repository", "project", "document"]',
    )

    # LLM config
    system_prompt = models.TextField(
        default=(
            "Eres Ecofilia, un asistente especializado en sostenibilidad. "
            "Responde siempre basándote en los documentos provistos y cita las fuentes."
        )
    )
    # For QUICK: full prompt template. Use {{context}} for doc content,
    # {{extra_instructions}} for user overrides.
    prompt_template = models.TextField(
        blank=True,
        help_text=(
            "For QUICK skills: use {{context}} to inject document content "
            "and {{extra_instructions}} for optional user instructions."
        ),
    )
    model = models.CharField(max_length=100, default=DEFAULT_MODEL)
    temperature = models.FloatField(default=0.3)

    # True = Ecofilia-provided, non-editable by regular users
    is_template = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("skill_type", "name")
        indexes = [models.Index(fields=("owner", "skill_type"))]

    def __str__(self) -> str:
        return f"{self.name} ({self.skill_type})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.name) or "skill"
        slug, counter = base[:255], 1
        while Skill.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            suffix = f"-{counter}"
            slug = f"{base[:255 - len(suffix)]}{suffix}"
            counter += 1
        return slug

    def can_edit(self, user) -> bool:
        if user.is_staff:
            return True
        if self.is_template:
            return False
        return self.owner_id == user.id


# ---------------------------------------------------------------------------
# Copilot steps  (ordered sections for COPILOT skills)
# ---------------------------------------------------------------------------

class SkillStep(models.Model):
    skill = models.ForeignKey(Skill, related_name="steps", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    instructions = models.TextField(
        help_text="What the AI should produce for this section of the output."
    )
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("position",)
        unique_together = ("skill", "position")

    def __str__(self) -> str:
        return f"{self.skill.name} — Step {self.position}: {self.title}"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class SkillExecution(models.Model):
    """
    A single run of a Skill against a specific context.
    """
    skill = models.ForeignKey(Skill, related_name="executions", on_delete=models.CASCADE)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="skill_executions",
        on_delete=models.CASCADE,
    )

    # Context — exactly one should be set (or none for ANY context testing)
    repository = models.ForeignKey(
        "repository.Repository",
        related_name="skill_executions",
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    project = models.ForeignKey(
        "project.Project",
        related_name="skill_executions",
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    document = models.ForeignKey(
        "document.Document",
        related_name="skill_executions",
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    # Optional user-provided instructions that override / extend the skill
    extra_instructions = models.TextField(blank=True)

    # Execution state
    status = models.CharField(
        max_length=20, choices=ExecutionStatus.choices, default=ExecutionStatus.PENDING
    )

    # QUICK output: plain text (markdown)
    output = models.TextField(blank=True)

    # COPILOT output: {"steps": [{"step_id": 1, "title": "...", "content": "..."}]}
    output_structured = models.JSONField(default=dict, blank=True)

    # Snapshot of which documents were used (for reproducibility)
    document_snapshot = models.JSONField(default=list)

    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # token usage, timing, etc.

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "created_at")),
            models.Index(fields=("skill", "status")),
        ]

    def __str__(self) -> str:
        return f"Execution {self.id} — {self.skill.name} ({self.status})"

    @property
    def context_label(self) -> str:
        if self.repository_id:
            return f"Repository: {self.repository.name}"
        if self.project_id:
            return f"Project: {self.project.name}"
        if self.document_id:
            return f"Document: {self.document.name}"
        return "No context"
