from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0006_skill_default_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="skillexecution",
            name="output_mode",
            field=models.CharField(
                choices=[("text", "Text"), ("table", "Table")],
                default="text",
                help_text="Requested output shape for this execution (text or table).",
                max_length=20,
            ),
        ),
    ]
