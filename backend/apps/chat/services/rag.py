from __future__ import annotations

import os
from typing import Iterable, List

from django.db.models import Q, QuerySet
from pgvector.django import CosineDistance

from apps.document.models import Document, SmartChunk
from apps.document.utils.client_openia import embed_text

MAX_CONTEXT_CHUNKS = int(os.environ.get("CHAT_CONTEXT_CHUNKS", "4"))


def fetch_relevant_chunks(
    *,
    user,
    query_text: str,
    allowed_documents: QuerySet[Document],
    top_n: int | None = None,
    topics: list[str] | None = None,
    retrieval_strategy: str = "global",
    k_per_doc: int = 2,
    total_limit: int | None = None,
    max_chunks_per_doc: int | None = None,
) -> List[SmartChunk]:
    """
    Returns the most relevant chunks limited to the allowed documents for the session.
    """
    top_n = top_n or MAX_CONTEXT_CHUNKS
    total_limit = total_limit or top_n
    max_chunks_per_doc = max_chunks_per_doc or total_limit

    if not query_text:
        return []

    doc_ids = list(allowed_documents.values_list("id", flat=True))
    if not doc_ids:
        return []

    # Chunks sin embedding rompen CosineDistance en pgvector y provocan 500
    qs = SmartChunk.objects.filter(document_id__in=doc_ids).exclude(embedding__isnull=True)
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

    if topics:
        topic_filter = Q()
        for topic in topics:
            if topic:
                topic_filter |= Q(content__icontains=topic)
        if topic_filter:
            filtered_by_topics = qs.filter(topic_filter)
            if filtered_by_topics.exists():
                qs = filtered_by_topics

    if not qs.exists():
        return []

    if retrieval_strategy != "hybrid_per_document":
        return list(qs.top_similar(query_text, top_n=top_n))

    query_embedding = embed_text(query_text)
    if not query_embedding:
        return list(qs.top_similar(query_text, top_n=top_n))

    doc_ids = list(allowed_documents.values_list("id", flat=True))
    if not doc_ids:
        return []

    ranked_qs = qs.annotate(
        distance=CosineDistance("embedding", query_embedding)
    ).order_by("distance")

    # Phase 1: ensure recall coverage by taking top-k candidates per document.
    candidates: list[SmartChunk] = []
    safe_k_per_doc = max(1, k_per_doc)
    for doc_id in doc_ids:
        doc_top = list(ranked_qs.filter(document_id=doc_id)[:safe_k_per_doc])
        candidates.extend(doc_top)

    if not candidates:
        return []

    # Deduplicate candidates by chunk id while preserving best distance.
    by_id: dict[int, SmartChunk] = {}
    for chunk in candidates:
        existing = by_id.get(chunk.id)
        if existing is None:
            by_id[chunk.id] = chunk
            continue
        if getattr(chunk, "distance", 1.0) < getattr(existing, "distance", 1.0):
            by_id[chunk.id] = chunk

    # Phase 2: global rerank with per-document cap and total limit.
    merged = sorted(
        by_id.values(),
        key=lambda c: getattr(c, "distance", 1.0),
    )

    selected: list[SmartChunk] = []
    per_doc_counter: dict[int, int] = {}
    safe_per_doc_cap = max(1, max_chunks_per_doc)
    safe_total_limit = max(1, total_limit)
    for chunk in merged:
        doc_id = chunk.document_id
        used_for_doc = per_doc_counter.get(doc_id, 0)
        if used_for_doc >= safe_per_doc_cap:
            continue
        selected.append(chunk)
        per_doc_counter[doc_id] = used_for_doc + 1
        if len(selected) >= safe_total_limit:
            break

    return selected


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



