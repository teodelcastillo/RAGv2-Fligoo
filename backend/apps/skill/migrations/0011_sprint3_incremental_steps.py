"""
Sprint 3 — Incremental step output.

Adds SkillExecution.steps_completed so the runner can persist each copilot
step as it finishes. The frontend polls GET /executions/{id}/ and can render
steps progressively instead of waiting for the full run to complete.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0010_sprint1_sprint2_agentic"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillexecution",
            name="steps_completed",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text=(
                    "Number of copilot steps that have been written to output_structured so far."
                ),
            ),
        ),
    ]
