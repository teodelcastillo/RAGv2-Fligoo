"""
Sprint 4 — Human-in-the-loop.

- ExecutionStatus: adds 'awaiting_approval'.
  (Django TextChoices is defined in Python; DB only stores the string value
   so no ALTER is needed for the status field itself — it stays varchar(20).)

- SkillStep.approval_required: pause execution after this step and wait for
  the consultant to review, optionally edit, and approve before continuing.

- SkillExecution.current_step_position: which step position is currently
  awaiting approval (null when not paused).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0011_sprint3_incremental_steps"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillstep",
            name="approval_required",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, the copilot pauses after this step completes and waits for "
                    "the consultant to review, optionally edit, and approve before continuing."
                ),
            ),
        ),
        migrations.AddField(
            model_name="skillexecution",
            name="current_step_position",
            field=models.PositiveSmallIntegerField(
                null=True,
                blank=True,
                help_text=(
                    "When status=awaiting_approval, holds the position of the step currently "
                    "awaiting review. Null when the execution is not paused."
                ),
            ),
        ),
    ]
