# Generated manually for RepositoryShare

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("repository", "0002_repository_enabled_skills"),
    ]

    operations = [
        migrations.CreateModel(
            name="RepositoryShare",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("viewer", "Viewer"), ("editor", "Editor")], default="viewer", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shares",
                        to="repository.repository",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="repository_shares",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("repository", "user"),
                "unique_together": {("repository", "user")},
            },
        ),
    ]
