from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0008_document_content_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="smartchunk",
            name="context_summary",
            field=models.TextField(blank=True, default=""),
        ),
    ]
