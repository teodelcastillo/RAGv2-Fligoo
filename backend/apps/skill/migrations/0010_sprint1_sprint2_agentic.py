"""
Sprint 1 + Sprint 2 — Agentic capabilities.

Sprint 1:
  Skill.tools_enabled — opt-in function-calling loop.

Sprint 2A:
  Skill.research_phase_enabled — shared pre-research scratchpad for Copilot runs.
  Skill.research_queries — explicit research queries (auto-derived when empty).

Sprint 2B:
  SkillParameter — typed input parameters rendered as {{key}} template tokens.
  SkillExecution.input_values — values supplied at run time.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0009_merge_0008_skill_skillstep_native_table_output_0007_unmark_default_enabled_skills"),
    ]

    operations = [
        # ------------------------------------------------------------------ #
        # Sprint 1 — Tool use                                                 #
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name="skill",
            name="tools_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, the runner uses function-calling so the model can "
                    "invoke tools (search_more_context, calculate_ghg_emissions, etc.) "
                    "before producing its final answer."
                ),
            ),
        ),
        # ------------------------------------------------------------------ #
        # Sprint 2A — Research phase                                          #
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name="skill",
            name="research_phase_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Copilot only. When enabled, the runner executes a research phase that "
                    "builds a shared scratchpad from the full document corpus before running "
                    "authoring steps. Each step receives the scratchpad as additional context."
                ),
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="research_queries",
            field=models.JSONField(
                default=list,
                blank=True,
                help_text=(
                    "Optional list of explicit queries for the research phase. "
                    "If empty, queries are auto-derived from step titles and instructions."
                ),
            ),
        ),
        # ------------------------------------------------------------------ #
        # Sprint 2B — Typed parameters                                        #
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name="SkillParameter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "skill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="parameters",
                        to="skill.skill",
                    ),
                ),
                (
                    "key",
                    models.SlugField(
                        max_length=80,
                        help_text="Template variable name, e.g. 'framework' → {{framework}}.",
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        max_length=255,
                        help_text="Human-readable label shown in the UI.",
                    ),
                ),
                (
                    "param_type",
                    models.CharField(
                        choices=[
                            ("text", "Text"),
                            ("number", "Number"),
                            ("enum", "Enum (select)"),
                            ("boolean", "Boolean"),
                            ("date", "Date"),
                        ],
                        default="text",
                        max_length=20,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        help_text="Help text shown beneath the input field.",
                    ),
                ),
                (
                    "default_value",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        help_text="String representation of the default value.",
                    ),
                ),
                ("required", models.BooleanField(default=False)),
                (
                    "options",
                    models.JSONField(
                        default=list,
                        blank=True,
                        help_text="Allowed values for enum type. e.g. ['GRI', 'ISSB', 'CDP'].",
                    ),
                ),
                ("position", models.PositiveIntegerField(default=1)),
            ],
            options={
                "ordering": ("position",),
                "unique_together": {("skill", "key")},
            },
        ),
        migrations.AddField(
            model_name="skillexecution",
            name="input_values",
            field=models.JSONField(
                default=dict,
                blank=True,
                help_text=(
                    "Values for the skill's declared SkillParameter inputs, keyed by parameter key. "
                    "Rendered into the prompt via {{key}} template tokens."
                ),
            ),
        ),
    ]
