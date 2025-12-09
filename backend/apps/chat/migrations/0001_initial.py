from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.contrib.postgres.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("document", "0003_search_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatSession",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                (
                    "system_prompt",
                    models.TextField(
                        blank=True,
                        default="Eres un asistente especializado en aprovechar el contexto entregado. Responde únicamente con la información disponible y menciona la fuente.",
                    ),
                ),
                ("model", models.CharField(default="gpt-4o-mini", max_length=100)),
                ("temperature", models.FloatField(default=0.1)),
                ("language", models.CharField(default="es", max_length=16)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "allowed_documents",
                    models.ManyToManyField(
                        blank=True,
                        related_name="chat_sessions",
                        to="document.document",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="ChatMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("system", "System"),
                            ("user", "User"),
                            ("assistant", "Assistant"),
                        ],
                        max_length=20,
                    ),
                ),
                ("content", models.TextField()),
                (
                    "chunk_ids",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.IntegerField(),
                        blank=True,
                        default=list,
                        help_text="IDs de SmartChunk utilizados para esta respuesta.",
                        size=None,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="chat.chatsession",
                    ),
                ),
            ],
            options={
                "ordering": ("created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="chatsession",
            index=models.Index(
                fields=["owner", "created_at"], name="chat_chats_owner__35822a_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="chatmessage",
            index=models.Index(
                fields=["session", "created_at"], name="chat_chatm_session_feb991_idx"
            ),
        ),
    ]









