from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("document", "0005_document_metadata_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Repository",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("repo_type", models.CharField(
                    choices=[("public", "Public"), ("private", "Private")],
                    default="private",
                    max_length=20,
                )),
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField(blank=True, max_length=255, unique=True)),
                ("description", models.TextField(blank=True)),
                ("category", models.CharField(blank=True, max_length=255, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="repositories",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "repositories",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="RepositoryDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="repository_documents",
                        to="document.document",
                    ),
                ),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="repository_documents",
                        to="repository.repository",
                    ),
                ),
            ],
            options={
                "ordering": ("-added_at",),
                "unique_together": {("repository", "document")},
            },
        ),
        migrations.AddField(
            model_name="repository",
            name="documents",
            field=models.ManyToManyField(
                blank=True,
                related_name="repositories",
                through="repository.RepositoryDocument",
                to="document.document",
            ),
        ),
        migrations.AddIndex(
            model_name="repository",
            index=models.Index(fields=["repo_type"], name="repository__repo_ty_idx"),
        ),
        migrations.AddIndex(
            model_name="repository",
            index=models.Index(fields=["owner", "created_at"], name="repository__owner_cr_idx"),
        ),
    ]
