"""
Management command: backfill Document.region for documents that have no region set.

Scans Document.name and (if needed) Document.extracted_text to auto-detect the
country / region using the same regex heuristics used during ingestion.

Usage
-----
# Dry-run (shows what would be set, writes nothing):
python manage.py backfill_document_regions --dry-run

# Live run (sets region on all untagged documents):
python manage.py backfill_document_regions

# Only process a specific document by ID:
python manage.py backfill_document_regions --doc-id 42

# Limit how many docs to process (useful for staged rollout):
python manage.py backfill_document_regions --limit 100
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.document.models import Document
from apps.document.utils.region_detector import detect_country_region


class Command(BaseCommand):
    help = "Auto-detect and backfill Document.region for documents without a region."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be changed without writing to the database.",
        )
        parser.add_argument(
            "--doc-id",
            type=int,
            default=None,
            help="Only process a single document with this ID.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of documents to process.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            default=False,
            help="Also overwrite documents that already have a region set.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        doc_id: int | None = options["doc_id"]
        limit: int | None = options["limit"]
        overwrite: bool = options["overwrite"]

        qs = Document.objects.all()

        if doc_id is not None:
            qs = qs.filter(pk=doc_id)
            if not qs.exists():
                raise CommandError(f"Document with id={doc_id} not found.")

        if not overwrite:
            # Only process documents that have no region (null or blank string).
            qs = qs.filter(region__isnull=True) | qs.filter(region="")
            # Django ORM doesn't support OR directly on the same queryset easily;
            # use Q objects.
            from django.db.models import Q
            qs = Document.objects.filter(Q(region__isnull=True) | Q(region=""))
            if doc_id is not None:
                qs = qs.filter(pk=doc_id)

        total = qs.count()
        if limit:
            qs = qs[:limit]

        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Processing {min(total, limit or total)} / {total} documents "
            f"({'overwrite=on' if overwrite else 'only untagged'})…"
        )

        detected = 0
        skipped = 0

        for doc in qs.iterator(chunk_size=200):
            country = detect_country_region(doc.name or "", doc.extracted_text or "")
            if country:
                detected += 1
                if dry_run:
                    self.stdout.write(
                        f"  [dry-run] doc #{doc.id} '{doc.name}' → {country!r}"
                    )
                else:
                    Document.objects.filter(pk=doc.pk).update(region=country)
                    self.stdout.write(
                        self.style.SUCCESS(f"  doc #{doc.id} '{doc.name}' → {country!r}")
                    )
            else:
                skipped += 1
                self.stdout.write(
                    f"  doc #{doc.id} '{doc.name}' → (not detected)"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'[DRY RUN] ' if dry_run else ''}Done. "
                f"Detected: {detected}, Not detected: {skipped}."
            )
        )
