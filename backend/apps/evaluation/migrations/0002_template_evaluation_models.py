# Generated manually for template-based evaluation dashboards

import uuid
from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("evaluation", "0001_initial"),
        ("project", "0002_rename_project_own_created_aa3a57_idx_project_pro_owner_i_bc287f_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluationTemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.TextField()),
                ("description", models.TextField(blank=True)),
                ("methodology", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "evaluation_templates",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="EvaluationPillarTemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.TextField()),
                ("name", models.TextField()),
                ("weight", models.DecimalField(decimal_places=4, default=Decimal("1"), max_digits=5)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pillars",
                        to="evaluation.evaluationtemplate",
                    ),
                ),
            ],
            options={
                "db_table": "evaluation_pillars",
                "ordering": ("template", "code"),
                "unique_together": {("template", "code")},
            },
        ),
        migrations.CreateModel(
            name="EvaluationKPITemplate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.TextField()),
                ("name", models.TextField()),
                ("max_score", models.IntegerField(default=3)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "pillar",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="kpis",
                        to="evaluation.evaluationpillartemplate",
                    ),
                ),
            ],
            options={
                "db_table": "evaluation_kpis",
                "ordering": ("pillar", "code"),
                "unique_together": {("pillar", "code")},
            },
        ),
        migrations.CreateModel(
            name="TemplateEvaluationRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("executed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("running", "En ejecución"),
                            ("completed", "Completado"),
                            ("failed", "Fallido"),
                        ],
                        default="completed",
                        max_length=20,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="template_evaluation_runs",
                        to="project.project",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runs",
                        to="evaluation.evaluationtemplate",
                    ),
                ),
            ],
            options={
                "db_table": "template_evaluation_runs",
                "ordering": ("-executed_at",),
            },
        ),
        migrations.CreateModel(
            name="TemplateEvaluationRunScore",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("score", models.DecimalField(decimal_places=2, max_digits=4)),
                ("evidence", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "kpi",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="run_scores",
                        to="evaluation.evaluationkpitemplate",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scores",
                        to="evaluation.templateevaluationrun",
                    ),
                ),
            ],
            options={
                "db_table": "template_evaluation_run_scores",
                "unique_together": {("run", "kpi")},
            },
        ),
        migrations.AddIndex(
            model_name="templateevaluationrun",
            index=models.Index(fields=["project"], name="template_eva_project__idx"),
        ),
        migrations.AddIndex(
            model_name="templateevaluationrun",
            index=models.Index(fields=["template"], name="template_eva_template_idx"),
        ),
        migrations.AddIndex(
            model_name="templateevaluationrun",
            index=models.Index(fields=["executed_at"], name="template_eva_executed_idx"),
        ),
    ]
