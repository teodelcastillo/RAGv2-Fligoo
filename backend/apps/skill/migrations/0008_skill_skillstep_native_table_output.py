from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0007_skillexecution_output_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="skill",
            name="default_output_mode",
            field=models.CharField(
                choices=[("text", "Text"), ("table", "Table")],
                default="text",
                help_text=(
                    "Default output mode for this skill. When set to 'table', the skill "
                    "produces structured tabular output using the configured table_schema."
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="skill",
            name="table_schema",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Persistent schema for tabular output. Expected shape: "
                    '{"name": str, "description": str, "columns": [TableColumn]}.'
                ),
            ),
        ),
        migrations.AddField(
            model_name="skillstep",
            name="output_mode",
            field=models.CharField(
                choices=[("text", "Text"), ("table", "Table")],
                default="text",
                help_text=(
                    "Output mode for this step. When set to 'table', the step must define "
                    "a table_schema so the runner produces structured rows."
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="skillstep",
            name="table_schema",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Persistent schema for tabular output of this step. Expected shape: "
                    '{"name": str, "description": str, "columns": [TableColumn]}.'
                ),
            ),
        ),
    ]
