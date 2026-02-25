"""
Template-based evaluation models for dashboards.
These models support fixed evaluation templates (e.g. ASG Allen Manza) with pillars and KPIs,
and runs executed per project.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.project.models import Project


class EvaluationTemplate(models.Model):
    """Fixed evaluation template (e.g. ASG Allen Manza)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    description = models.TextField(blank=True)
    methodology = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluation_templates"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class EvaluationPillarTemplate(models.Model):
    """Pillar belonging to a template (e.g. Ambiental, Social, Gobernanza)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        EvaluationTemplate,
        on_delete=models.CASCADE,
        related_name="pillars",
    )
    code = models.TextField()
    name = models.TextField()
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("1"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluation_pillars"
        ordering = ("template", "code")
        unique_together = ("template", "code")

    def __str__(self) -> str:
        return f"{self.code} - {self.name} ({self.template.name})"


class EvaluationKPITemplate(models.Model):
    """KPI belonging to a pillar (e.g. A1 Cambio climático)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pillar = models.ForeignKey(
        EvaluationPillarTemplate,
        on_delete=models.CASCADE,
        related_name="kpis",
    )
    code = models.TextField()
    name = models.TextField()
    max_score = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluation_kpis"
        ordering = ("pillar", "code")
        unique_together = ("pillar", "code")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class TemplateEvaluationRunStatus(models.TextChoices):
    PENDING = "pending", _("Pendiente")
    RUNNING = "running", _("En ejecución")
    COMPLETED = "completed", _("Completado")
    FAILED = "failed", _("Fallido")


class TemplateEvaluationRun(models.Model):
    """Execution of a template evaluation on a project."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="template_evaluation_runs",
    )
    template = models.ForeignKey(
        EvaluationTemplate,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    executed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=TemplateEvaluationRunStatus.choices,
        default=TemplateEvaluationRunStatus.COMPLETED,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "template_evaluation_runs"
        ordering = ("-executed_at",)
        indexes = [
            models.Index(fields=["project"]),
            models.Index(fields=["template"]),
            models.Index(fields=["executed_at"]),
        ]

    def __str__(self) -> str:
        return f"Run {self.id} - {self.project.name} ({self.template.name})"

    def can_view(self, user) -> bool:
        return self.project.can_view(user)


class TemplateEvaluationRunScore(models.Model):
    """KPI score for a template evaluation run."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        TemplateEvaluationRun,
        on_delete=models.CASCADE,
        related_name="scores",
    )
    kpi = models.ForeignKey(
        EvaluationKPITemplate,
        on_delete=models.CASCADE,
        related_name="run_scores",
    )
    score = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    evidence = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "template_evaluation_run_scores"
        unique_together = ("run", "kpi")

    def __str__(self) -> str:
        return f"Score {self.score} - {self.kpi.code} (run {self.run_id})"
