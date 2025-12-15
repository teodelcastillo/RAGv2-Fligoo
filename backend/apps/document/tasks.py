from __future__ import annotations
import logging
import os
import tempfile
from celery import shared_task
from django.db import transaction
from apps.document.models import Document, SmartChunk, ChunkingStatus
from apps.document.utils.chunker import chunk_text_and_embed
from apps.document.utils.parser import parse_file

logger = logging.getLogger(__name__)

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

        chunks = chunk_text_and_embed(text, doc.id) or []
        if not chunks:
            logger.warning("No chunks produced for document %s.", doc_id)

        with transaction.atomic():
            if chunks:
                SmartChunk.objects.bulk_create(chunks, ignore_conflicts=True, batch_size=1000)

            (Document.objects
                .filter(pk=doc_id)
                .update(
                    extracted_text=text,
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
