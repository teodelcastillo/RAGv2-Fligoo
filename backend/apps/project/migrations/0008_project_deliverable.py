"""
Multi-deliverable support: introduces ``ProjectDeliverable`` between
``Project`` and ``ProjectSection``. Migrates every existing project so it
has exactly one ``is_primary=True`` deliverable named "Entregable
principal" that owns all current sections.
"""
from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models
from django.utils.text import slugify


def _generate_slug(project_id, name, used_slugs):
    base = slugify(name) or "entregable"
    base = base[:255]
    slug = base
    counter = 1
    key = (project_id, slug)
    while key in used_slugs:
        suffix = f"-{counter}"
        slug = f"{base[: 255 - len(suffix)]}{suffix}"
        counter += 1
        key = (project_id, slug)
    used_slugs.add(key)
    return slug


def backfill_primary_deliverables(apps, schema_editor):
    Project = apps.get_model("project", "Project")
    ProjectDeliverable = apps.get_model("project", "ProjectDeliverable")
    ProjectSection = apps.get_model("project", "ProjectSection")

    used_slugs: set[tuple[int, str]] = set()
    for project in Project.objects.all().iterator():
        slug = _generate_slug(project.id, "Entregable principal", used_slugs)
        deliverable = ProjectDeliverable.objects.create(
            project=project,
            name="Entregable principal",
            slug=slug,
            template_id=project.structure_template_id,
            is_primary=True,
            position=1,
            status="draft",
        )
        # Move all sections of this project into the new deliverable.
        # Copilot ChatSessions are linked separately by chat/0006 so this
        # migration has no cross-app dependency on the chat side.
        ProjectSection.objects.filter(project=project).update(
            deliverable=deliverable,
        )


def remove_primary_deliverables(apps, schema_editor):
    ProjectDeliverable = apps.get_model("project", "ProjectDeliverable")
    ProjectSection = apps.get_model("project", "ProjectSection")
    # Reverse: clear deliverable refs so we can drop the table.
    ProjectSection.objects.update(deliverable=None)
    ProjectDeliverable.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0007_projectstructuretemplate_owner"),
        # ChatSession migration introducing the FK field is run as part of
        # this PR. The migration below adds the column on the chat side.
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectDeliverable",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(blank=True, max_length=255)),
                ("is_primary", models.BooleanField(default=False, help_text="Exactly one deliverable per project should be primary.")),
                ("position", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Draft"), ("final", "Final"), ("archived", "Archived")],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliverables",
                        to="project.project",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deliverables",
                        to="project.projectstructuretemplate",
                    ),
                ),
            ],
            options={
                "ordering": ("position", "created_at"),
                "unique_together": {("project", "slug"), ("project", "position")},
            },
        ),
        # Add nullable deliverable FK to ProjectSection so we can back-fill
        # before flipping the unique constraint.
        migrations.AddField(
            model_name="projectsection",
            name="deliverable",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Deliverable this section belongs to. Null only during "
                    "the migration window before back-filling."
                ),
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sections",
                to="project.projectdeliverable",
            ),
        ),
        # Run the data migration that creates one deliverable per project
        # and assigns existing sections + copilot sessions to it.
        migrations.RunPython(
            backfill_primary_deliverables,
            reverse_code=remove_primary_deliverables,
        ),
        # Now that every section has a deliverable, swap the unique
        # constraint from (project, position) to (deliverable, position).
        migrations.AlterUniqueTogether(
            name="projectsection",
            unique_together={("deliverable", "position")},
        ),
    ]
