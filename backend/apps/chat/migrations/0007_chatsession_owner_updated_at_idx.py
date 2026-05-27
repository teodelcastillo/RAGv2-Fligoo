from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0006_chatsession_deliverable"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="chatsession",
            index=models.Index(
                fields=["owner", "-updated_at"],
                name="chat_session_owner_upd_idx",
            ),
        ),
    ]
