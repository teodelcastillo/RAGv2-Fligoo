"""
Backfill contextual summaries for existing SmartChunks.

Dispatches one Celery task per document with pending chunks.

Usage:
  python manage.py backfill_chunk_context
  python manage.py backfill_chunk_context --doc-id 42
  python manage.py backfill_chunk_context --batch-size 100 --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.document.models import SmartChunk


class Command(BaseCommand):
    help = "Backfill context_summary (and re-embed) for SmartChunks that lack it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--doc-id",
            type=int,
            default=None,
            help="Process only this document ID.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Chunks per batch inside each Celery task (default 50).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show counts without dispatching any tasks.",
        )

    def handle(self, **options):
        doc_id = options["doc_id"]
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]

        qs = SmartChunk.objects.filter(context_summary="")
        if doc_id:
            qs = qs.filter(document_id=doc_id)

        doc_ids = list(qs.values_list("document_id", flat=True).distinct())
        total_chunks = qs.count()

        if not doc_ids:
            self.stdout.write(self.style.SUCCESS("No chunks pending backfill."))
            return

        self.stdout.write(
            f"Found {total_chunks} chunks across {len(doc_ids)} document(s)."
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no tasks dispatched."))
            return

        from apps.document.tasks import backfill_chunk_context_for_document

        for did in doc_ids:
            backfill_chunk_context_for_document.delay(did, batch_size)

        self.stdout.write(
            self.style.SUCCESS(
                f"Dispatched {len(doc_ids)} backfill task(s) to Celery."
            )
        )
