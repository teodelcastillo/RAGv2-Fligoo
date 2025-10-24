import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.document.models import Document, ChunkingStatus
from apps.document.tasks import process_document_chunks
from django.conf import settings

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Document)
def handle_document_post_save(sender, instance: Document, created: bool, **kwargs):
    logger.info("Document post_save triggered: id=%s, created=%s", instance.id, created)

    if not created or instance.chunking_done or instance.chunking_status == ChunkingStatus.DONE:
        return

    # Mark as pending so UI knows it's queued
    Document.objects.filter(pk=instance.pk).update(chunking_status=ChunkingStatus.PENDING)
    if settings.DEBUG:
        # In debug mode, process immediately (synchronously)
        process_document_chunks(instance.pk)
    else:
        transaction.on_commit(lambda: process_document_chunks.delay(instance.pk))
