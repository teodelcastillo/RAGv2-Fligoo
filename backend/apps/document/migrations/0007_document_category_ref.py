from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards_category_ref(apps, schema_editor):
    Document = apps.get_model("document", "Document")
    Category = apps.get_model("document", "Category")

    for doc in (
        Document.objects.exclude(category__isnull=True)
        .exclude(category="")
        .iterator()
    ):
        name = (doc.category or "").strip()
        if not name:
            continue
        # Match by owner and case-insensitive name; one Category per owner+name
        existing = Category.objects.filter(owner_id=doc.owner_id, name__iexact=name).first()
        if existing:
            doc.category_ref_id = existing.id
            doc.save(update_fields=["category_ref_id"])
            continue
        cat = Category(owner_id=doc.owner_id, name=name, parent_id=None)
        cat.save()
        doc.category_ref_id = cat.id
        doc.save(update_fields=["category_ref_id"])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0006_documentshare_category"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="category_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="document.category",
            ),
        ),
        migrations.AddIndex(
            model_name="document",
            index=models.Index(
                fields=["category_ref"],
                name="doc_doc_category_ref_id_idx",
            ),
        ),
        migrations.RunPython(forwards_category_ref, reverse_noop),
    ]
