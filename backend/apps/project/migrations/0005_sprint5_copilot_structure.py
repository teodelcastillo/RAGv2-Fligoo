from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0004_project_blueprint_document"),
    ]

    operations = [
        # --- ProjectStructureTemplate ---
        migrations.CreateModel(
            name="ProjectStructureTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(max_length=255, unique=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("name",)},
        ),
        # --- ProjectStructureSection ---
        migrations.CreateModel(
            name="ProjectStructureSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("position", models.PositiveIntegerField(default=1)),
                ("suggested_skill_slugs", models.JSONField(blank=True, default=list, help_text="Slugs of skills the copilot can suggest for this section.")),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sections",
                        to="project.projectstructuretemplate",
                    ),
                ),
            ],
            options={
                "ordering": ("position",),
                "unique_together": {("template", "position")},
            },
        ),
        # --- ProjectSection ---
        migrations.CreateModel(
            name="ProjectSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("position", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("not_started", "Not Started"), ("in_progress", "In Progress"), ("review", "Review"), ("completed", "Completed")], default="not_started", max_length=20)),
                ("notes", models.TextField(blank=True)),
                ("output_snapshot", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sections",
                        to="project.project",
                    ),
                ),
                (
                    "template_section",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="project.projectstructuresection",
                    ),
                ),
            ],
            options={
                "ordering": ("position",),
                "unique_together": {("project", "position")},
            },
        ),
        # --- New fields on Project ---
        migrations.AddField(
            model_name="project",
            name="structure_template",
            field=models.ForeignKey(
                blank=True,
                help_text="Structure template that defines the project's sections/phases.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="projects",
                to="project.projectstructuretemplate",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="context_notes",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Persistent context injected into every copilot prompt. Example: {"company": "Acme Corp", "sector": "Manufacturing", "framework": "GRI", "reporting_year": "2024"}',
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="copilot_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Whether the copilot assistant is active for this project.",
            ),
        ),
    ]
