from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("skill", "0013_skillexecution_editable_outputs"),
    ]

    operations = [
        migrations.AddField(
            model_name="skill",
            name="pinned_document_slugs",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Default document filter. Empty = all context documents.",
            ),
        ),
    ]
