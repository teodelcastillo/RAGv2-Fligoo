"""
Sprint — Editable execution outputs.

- SkillExecution.edited_output / edited_at / edited_by: latest user-edited
  markdown of the AI output. When non-empty the UI treats this as the current
  content; the raw AI output stays untouched so the user can always diff or
  revert.
- New SkillExecutionVersion model: immutable snapshots of edited_output
  taken on each save, so users can browse and restore previous iterations.
"""
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0012_sprint4_human_in_the_loop"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="skillexecution",
            name="edited_output",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Latest user-edited markdown of this execution's result. Empty means "
                    "the user has not modified the AI-generated output yet."
                ),
            ),
        ),
        migrations.AddField(
            model_name="skillexecution",
            name="edited_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="skillexecution",
            name="edited_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="edited_skill_executions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="SkillExecutionVersion",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version_number", models.PositiveIntegerField()),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        help_text="Optional short note the user attaches to this save point.",
                        max_length=120,
                    ),
                ),
                (
                    "content",
                    models.TextField(
                        help_text="Markdown snapshot of edited_output at the time of save.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="skill_execution_versions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "execution",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="versions",
                        to="skill.skillexecution",
                    ),
                ),
            ],
            options={
                "ordering": ("-version_number",),
                "unique_together": {("execution", "version_number")},
                "indexes": [
                    models.Index(
                        fields=["execution", "version_number"],
                        name="skill_skil_executi_v_idx",
                    ),
                ],
            },
        ),
    ]
