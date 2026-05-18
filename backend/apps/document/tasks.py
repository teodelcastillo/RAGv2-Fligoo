from __future__ import annotations
import logging
import os
import tempfile
import time
from celery import shared_task
from django.db import transaction
from apps.document.models import Document, SmartChunk, ChunkingStatus
from apps.document.utils.chunker import chunk_text_and_embed
from apps.document.utils.client_openia import (
    embed_text,
    generate_chunk_context,
    generate_document_content_summary,
)
from apps.document.utils.parser import parse_file

logger = logging.getLogger(__name__)


def _document_auto_summary_enabled() -> bool:
    return str(os.environ.get("DOCUMENT_AUTO_SUMMARY", "1")).lower() in (
        "1",
        "true",
        "yes",
    )

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_document_chunks(self, doc_id: int) -> str:
    tmp_path = None
    try:
        doc = Document.objects.get(pk=doc_id)

        # Skip if already processed
        if doc.chunking_done or doc.chunking_status == ChunkingStatus.DONE:
            logger.info("Document %s already processed; skipping.", doc_id)
            return "already_done"

        # Mark as processing
        Document.objects.filter(pk=doc_id).update(chunking_status=ChunkingStatus.PROCESSING)

        # Ensure there's a file
        if not doc.file:
            raise FileNotFoundError("Document has no attached file.")

        # --- Create a temp file with the SAME extension so parse_file() can detect type ---
        # Prefer extension from the stored file key; fallback to doc.name if needed
        ext = os.path.splitext(doc.file.name or "")[1]
        if not ext:
            ext = os.path.splitext(doc.name or "")[1]

        # Stream from storage (S3/local) to temp file with preserved suffix
        with doc.file.open("rb") as f_src, tempfile.NamedTemporaryFile(suffix=ext or "", delete=False) as f_tmp:
            tmp_path = f_tmp.name
            for chunk in iter(lambda: f_src.read(1024 * 1024), b""):  # 1MB chunks
                f_tmp.write(chunk)

        text = parse_file(tmp_path) or ""

        content_summary = ""
        if _document_auto_summary_enabled() and text.strip():
            try:
                content_summary = generate_document_content_summary(
                    title=doc.name or doc.slug or "Sin título",
                    body_text=text,
                )
            except Exception as sum_exc:
                logger.warning(
                    "Document %s: resumen automático omitido (%s)",
                    doc_id,
                    sum_exc,
                )

        chunks = chunk_text_and_embed(
            text,
            doc.id,
            document_name=doc.name or "",
            content_summary=content_summary or None,
        ) or []
        if not chunks:
            logger.warning("No chunks produced for document %s.", doc_id)

        with transaction.atomic():
            if chunks:
                SmartChunk.objects.bulk_create(chunks, ignore_conflicts=True, batch_size=1000)

            (Document.objects
                .filter(pk=doc_id)
                .update(
                    extracted_text=text,
                    content_summary=content_summary,
                    chunking_done=True,
                    chunking_status=ChunkingStatus.DONE,
                    last_error=""
                ))

        logger.info("Chunking completed for document %s (%d chunks).", doc_id, len(chunks))
        return "ok"

    except Document.DoesNotExist:
        logger.error("Document %s not found for chunking.", doc_id)
        return "missing"

    except Exception as e:
        logger.exception("Failed to chunk document %s: %s", doc_id, e)
        try:
            Document.objects.filter(pk=doc_id).update(
                last_error=str(e),
                chunking_status=ChunkingStatus.ERROR
            )
        except Exception:
            pass
        return "error"

    finally:
        # Clean up temp file if created
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                logger.warning("Could not remove temp file %s", tmp_path)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def backfill_chunk_context_for_document(self, doc_id: int, batch_size: int = 50) -> str:
    try:
        doc = Document.objects.get(pk=doc_id)
    except Document.DoesNotExist:
        logger.error("Backfill: document %s not found.", doc_id)
        return "missing"

    doc_name = doc.name or doc.slug or ""
    doc_summary = doc.content_summary or ""

    qs = SmartChunk.objects.filter(
        document_id=doc_id,
        context_summary="",
    ).order_by("chunk_index")

    total = qs.count()
    if total == 0:
        logger.info("Backfill: document %s has no chunks pending.", doc_id)
        return "already_done"

    logger.info("Backfill: document %s — %d chunks pending.", doc_id, total)
    processed = 0

    while True:
        batch = list(qs[:batch_size])
        if not batch:
            break

        for chunk in batch:
            ctx = generate_chunk_context(
                chunk_content=chunk.content or "",
                doc_name=doc_name,
                doc_summary=doc_summary,
                chunk_index=chunk.chunk_index,
            )
            if not ctx:
                continue

            embed_input = f"{ctx}\n\n{chunk.content}"
            new_embedding = embed_text(embed_input)

            SmartChunk.objects.filter(pk=chunk.pk).update(
                context_summary=ctx,
                embedding=new_embedding,
            )
            processed += 1
            time.sleep(0.5)

    logger.info(
        "Backfill: document %s complete — %d/%d chunks enriched.",
        doc_id, processed, total,
    )
    return f"ok:{processed}/{total}"
