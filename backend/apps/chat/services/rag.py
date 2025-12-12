from __future__ import annotations

import os
from typing import Iterable, List

from django.db.models import Q, QuerySet

from apps.document.models import Document, SmartChunk

MAX_CONTEXT_CHUNKS = int(os.environ.get("CHAT_CONTEXT_CHUNKS", "4"))


def fetch_relevant_chunks(
    *,
    user,
    query_text: str,
    allowed_documents: QuerySet[Document],
    top_n: int | None = None,
) -> List[SmartChunk]:
    """
    Returns the most relevant chunks limited to the allowed documents for the session.
    """
    top_n = top_n or MAX_CONTEXT_CHUNKS

    if not query_text:
        return []

    doc_ids = list(allowed_documents.values_list("id", flat=True))
    if not doc_ids:
        return []

    qs = SmartChunk.objects.filter(document_id__in=doc_ids)
    if not user.is_staff:
        # Incluir chunks de documentos propios, públicos, compartidos y de proyectos compartidos
        from apps.project.models import ProjectShare
        shared_project_ids = ProjectShare.objects.filter(
            user=user
        ).values_list('project_id', flat=True)
        qs = qs.filter(
            Q(document__owner=user) 
            | Q(document__is_public=True) 
            | Q(document__shares__user=user)
            | Q(document__projects__id__in=shared_project_ids)
        ).distinct()

    return list(qs.top_similar(query_text, top_n=top_n))


def build_context_block(chunks: Iterable[SmartChunk]) -> str:
    sections = []
    for chunk in chunks:
        sections.append(
            (
                f"Fuente: {chunk.document.name} (slug: {chunk.document.slug}, "
                f"chunk #{chunk.chunk_index})\n{chunk.content.strip()}"
            )
        )
    return "\n\n".join(sections).strip()



