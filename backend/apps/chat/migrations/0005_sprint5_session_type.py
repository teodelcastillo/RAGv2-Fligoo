from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0004_chatsession_primary_document_project"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="session_type",
            field=models.CharField(
                choices=[("standard", "Standard"), ("copilot", "Copilot")],
                default="standard",
                max_length=20,
            ),
        ),
    ]
