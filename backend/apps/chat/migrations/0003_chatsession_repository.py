from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_rename_chat_chatm_session_feb991_idx_chat_chatme_session_70d41b_idx_and_more"),
        ("repository", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="repository",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="chat_sessions",
                to="repository.repository",
                help_text="Repositorio al que pertenece esta sesión de chat (si aplica)",
            ),
        ),
        migrations.AddIndex(
            model_name="chatsession",
            index=models.Index(
                fields=["repository", "owner", "created_at"],
                name="chat_chats_reposit_owner_idx",
            ),
        ),
    ]
