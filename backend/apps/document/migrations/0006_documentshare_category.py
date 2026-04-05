from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0005_document_metadata_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS document_documentshare (
                    id bigserial PRIMARY KEY,
                    role varchar(20) NOT NULL DEFAULT 'viewer',
                    created_at timestamptz NOT NULL DEFAULT now(),
                    document_id bigint NOT NULL REFERENCES document_document(id) ON DELETE CASCADE,
                    user_id bigint NOT NULL REFERENCES user_user(id) ON DELETE CASCADE,
                    UNIQUE (document_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS document_documentshare_document_id
                    ON document_documentshare (document_id);
                CREATE INDEX IF NOT EXISTS document_documentshare_user_id
                    ON document_documentshare (user_id);

                CREATE TABLE IF NOT EXISTS document_category (
                    id bigserial PRIMARY KEY,
                    name varchar(255) NOT NULL,
                    slug varchar(255) NOT NULL UNIQUE,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    owner_id bigint NOT NULL REFERENCES user_user(id) ON DELETE CASCADE,
                    parent_id bigint REFERENCES document_category(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS document_category_owner_id
                    ON document_category (owner_id);
                CREATE INDEX IF NOT EXISTS document_category_parent_id
                    ON document_category (parent_id);
            """,
            reverse_sql="""
                DROP TABLE IF EXISTS document_category;
                DROP TABLE IF EXISTS document_documentshare;
            """,
            state_operations=[
                migrations.CreateModel(
                    name="DocumentShare",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("role", models.CharField(choices=[("viewer", "Viewer"), ("editor", "Editor")], default="viewer", max_length=20)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shares", to="document.document")),
                        ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="document_shares", to=settings.AUTH_USER_MODEL)),
                    ],
                    options={"ordering": ("document", "user"), "unique_together": {("document", "user")}},
                ),
                migrations.CreateModel(
                    name="Category",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("name", models.CharField(max_length=255)),
                        ("slug", models.SlugField(blank=True, max_length=255, unique=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="categories", to=settings.AUTH_USER_MODEL)),
                        ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="children", to="document.category")),
                    ],
                    options={"ordering": ("name",), "verbose_name_plural": "categories"},
                ),
            ],
        ),
    ]
