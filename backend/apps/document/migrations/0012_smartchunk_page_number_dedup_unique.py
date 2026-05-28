"""
Add page_number field to SmartChunk, remove duplicate (document, chunk_index) rows,
and enforce a unique_together constraint to prevent future duplicates.

Background
----------
SQS standard queues guarantee at-least-once delivery. When a Celery worker is slow
to acknowledge a message, SQS redelivers it, causing process_document_chunks to run
twice for the same document. Without a unique constraint the second run inserts
duplicate rows silently (bulk_create ignore_conflicts had nothing to conflict on).

Migration steps
---------------
1. Add page_number (nullable IntegerField).
2. RunPython: for each (document_id, chunk_index) pair that has more than one row,
   keep the one with the lowest id (the first inserted) and delete the rest.
3. AlterUniqueTogether: add the constraint so future duplicates are rejected at
   the DB level.
"""

from django.db import migrations, models


def remove_duplicate_chunks(apps, schema_editor):
    """Keep the first-inserted chunk (lowest id) per (document_id, chunk_index)."""
    SmartChunk = apps.get_model("document", "SmartChunk")
    from django.db.models import Min

    # IDs to keep: one per (document_id, chunk_index)
    keep_ids = (
        SmartChunk.objects
        .values("document_id", "chunk_index")
        .annotate(min_id=Min("id"))
        .values_list("min_id", flat=True)
    )
    deleted, _ = SmartChunk.objects.exclude(id__in=list(keep_ids)).delete()
    if deleted:
        import logging
        logging.getLogger(__name__).info(
            "Dedup migration: deleted %d duplicate SmartChunk rows.", deleted
        )


class Migration(migrations.Migration):

    dependencies = [
        ("document", "0011_smartchunk_embedding_hnsw_index"),
    ]

    operations = [
        # 1. Add page_number field
        migrations.AddField(
            model_name="smartchunk",
            name="page_number",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="Página del documento de origen (1-based). Null para docs sin información de página.",
            ),
        ),
        # 2. Remove existing duplicate rows before adding the unique constraint
        migrations.RunPython(
            remove_duplicate_chunks,
            reverse_code=migrations.RunPython.noop,
        ),
        # 3. Enforce uniqueness going forward
        migrations.AlterUniqueTogether(
            name="smartchunk",
            unique_together={("document", "chunk_index")},
        ),
    ]
