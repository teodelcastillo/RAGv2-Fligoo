"""Adds optional deliverable FK to ChatSession (copilot scope).

Runs after ``project.0008_project_deliverable`` so the foreign key can
point at the newly-created ``ProjectDeliverable`` model, and backfills
existing copilot sessions so they keep working with the multi-deliverable
data model.
"""
from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def link_copilot_sessions_to_primary(apps, schema_editor):
    ChatSession = apps.get_model("chat", "ChatSession")
    ProjectDeliverable = apps.get_model("project", "ProjectDeliverable")

    # Map project_id -> primary deliverable id once to avoid N queries.
    primary_by_project = dict(
        ProjectDeliverable.objects.filter(is_primary=True).values_list(
            "project_id", "id",
        )
    )
    sessions = ChatSession.objects.filter(
        session_type="copilot", project__isnull=False, deliverable__isnull=True,
    )
    for session in sessions.iterator():
        primary_id = primary_by_project.get(session.project_id)
        if primary_id is not None:
            session.deliverable_id = primary_id
            session.save(update_fields=["deliverable"])


def unlink_copilot_sessions(apps, schema_editor):
    ChatSession = apps.get_model("chat", "ChatSession")
    ChatSession.objects.filter(deliverable__isnull=False).update(deliverable=None)


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_sprint5_session_type"),
        # Depends on the deliverable model being available.
        ("project", "0008_project_deliverable"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="deliverable",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="chat_sessions",
                to="project.projectdeliverable",
                help_text=(
                    "Entregable activo al que pertenece esta sesión de "
                    "copilot. Solo aplica a sesiones de copilot dentro de "
                    "un proyecto."
                ),
            ),
        ),
        migrations.RunPython(
            link_copilot_sessions_to_primary,
            reverse_code=unlink_copilot_sessions,
        ),
    ]
