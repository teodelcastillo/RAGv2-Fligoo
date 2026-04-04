from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0003_chatsession_repository"),
        ("document", "0005_document_metadata_fields"),
        ("project", "0002_rename_project_own_created_aa3a57_idx_project_pro_owner_i_bc287f_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="primary_document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="primary_chat_session",
                to="document.document",
                help_text="Documento principal asociado a esta sesión de chat",
            ),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="chat_sessions",
                to="project.project",
                help_text="Proyecto al que pertenece esta sesión de chat (si aplica)",
            ),
        ),
        migrations.AddIndex(
            model_name="chatsession",
            index=models.Index(
                fields=["primary_document"],
                name="chat_chats_primary_doc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="chatsession",
            index=models.Index(
                fields=["project", "owner", "created_at"],
                name="chat_chats_project_owner_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatsession",
            constraint=models.UniqueConstraint(
                condition=models.Q(primary_document__isnull=False),
                fields=["primary_document", "owner"],
                name="unique_primary_document_per_user",
            ),
        ),
    ]
