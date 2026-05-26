"""
RAG entry points for the chat layer.

This module hosts:
- ``fetch_relevant_chunks``: legacy vector-first retriever, kept for backward
  compatibility with existing call sites and tests.
- ``retrieve_for_chat``: the new pipeline orchestrator (hybrid retrieval, RRF,
  optional LLM reranker, diversity selection, citation-ready context block).
- ``build_context_block``: proxy to ``context_builder.build_context_block`` so
  existing imports keep working.

Design notes:
- ``retrieve_for_chat`` calls ``fetch_relevant_chunks`` inside this module for
  the vector branch. Tests can keep patching ``apps.chat.services.rag.fetch_relevant_chunks``
  and the patch is honored at call time.
- All optional steps (LLM reranker, MMR, query expansion) are gated by env flags
  so the pipeline degrades gracefully when external services are off.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, List

from django.db.models import Q, QuerySet
from pgvector.django import CosineDistance

from apps.chat.services.context_builder import (
    build_citation_prompt,
    build_context_block as _build_context_block,
    is_mmr_enabled,
    mmr_select,
)
from apps.chat.services.query_analysis import (
    COVERAGE_MODE_ALL,
    QUERY_TYPE_PANORAMA,
    QueryAnalysis,
    apply_response_mode_override,
    build_query_set,
    classify_query,
    classify_query_hybrid,
)
from apps.chat.services.reranker import is_reranker_enabled, llm_rerank
from apps.chat.services.retrieval import cap_per_document, lexical_search, rrf_fuse
from apps.document.models import Document, SmartChunk
from apps.document.utils.client_openia import embed_text

logger = logging.getLogger(__name__)


MAX_CONTEXT_CHUNKS = int(os.environ.get("CHAT_CONTEXT_CHUNKS", "8"))
RAG_RERANK_POOL = int(os.environ.get("RAG_RERANK_POOL", "20"))
RAG_VECTOR_POOL_MULTIPLIER = float(os.environ.get("RAG_VECTOR_POOL_MULTIPLIER", "2.5"))
RAG_LEXICAL_POOL_MULTIPLIER = float(os.environ.get("RAG_LEXICAL_POOL_MULTIPLIER", "2.0"))
RAG_ALL_DOCS_MIN_COVERAGE_RATIO = float(
    os.environ.get("RAG_ALL_DOCS_MIN_COVERAGE_RATIO", "1.0")
)


GENERAL_QUERY_PATTERNS = (
    r"\b(resumen|panorama|vision|visión)\b",
    r"\b(general|global|integral|completo)\b",
    r"\b(todo|toda|todos|todas)\b",
    r"\b(base documental|documentacion|documentación)\b",
    r"\b(overall|high[- ]level|across)\b",
)


def is_general_query(query_text: str) -> bool:
    """Backward-compatible heuristic kept for legacy callers."""
    text = (query_text or "").strip().lower()
    if not text:
        return False
    if len(text.split()) >= 18:
        return True
    return any(re.search(pattern, text) for pattern in GENERAL_QUERY_PATTERNS)


# ---------------------------------------------------------------------------
# Public dataclass used by callers that want full pipeline diagnostics
# ---------------------------------------------------------------------------


@dataclass
class RetrievalResult:
    chunks: List[SmartChunk] = field(default_factory=list)
    context_block: str = ""
    analysis: QueryAnalysis | None = None
    diagnostics: dict = field(default_factory=dict)
    recommended_documents: list[dict] = field(default_factory=list)

    @property
    def chunk_ids(self) -> List[int]:
        return [c.id for c in self.chunks]

    @property
    def covered_document_ids(self) -> set:
        return {c.document_id for c in self.chunks}


def suggest_related_library_documents(
    *,
    user,
    query_text: str,
    exclude_document_ids: Iterable[int],
    top_n: int | None = None,
    chunk_pool: int | None = None,
    doc_pool: int | None = None,
) -> list[dict]:
    """
    Busca en toda la biblioteca accesible fragmentos similares a la pregunta,
    excluyendo documentos ya vinculados a la sesión/proyecto. Devuelve filas
    ``{id, slug, name, relevance_score}`` para mostrar como "documentos relacionados".
    """
    from apps.document.services import accessible_library_documents

    text = (query_text or "").strip()
    if not text:
        return []

    exclude = {int(x) for x in exclude_document_ids}
    top_n = top_n or int(os.environ.get("CHAT_LIBRARY_RECOMMEND_TOP_DOCS", "5"))
    chunk_pool = chunk_pool or int(os.environ.get("CHAT_LIBRARY_RECOMMEND_CHUNK_POOL", "56"))
    doc_pool = doc_pool or int(os.environ.get("CHAT_LIBRARY_RECOMMEND_DOC_POOL", "500"))

    lib = accessible_library_documents(user).exclude(id__in=exclude)
    lib = lib.filter(chunks__embedding__isnull=False).distinct()
    candidate_ids = list(lib.values_list("id", flat=True)[:doc_pool])
    if not candidate_ids:
        return []

    chunk_qs = SmartChunk.objects.filter(document_id__in=candidate_ids).exclude(
        embedding__isnull=True
    )
    if not user.is_staff:
        from apps.project.models import ProjectShare

        shared_project_ids = ProjectShare.objects.filter(user=user).values_list(
            "project_id", flat=True
        )
        chunk_qs = chunk_qs.filter(
            Q(document__owner=user)
            | Q(document__is_public=True)
            | Q(document__shares__user=user)
            | Q(document__projects__id__in=shared_project_ids)
        ).distinct()

    chunks = list(chunk_qs.top_similar(text, top_n=chunk_pool))
    if not chunks:
        return []

    doc_scores: dict[int, float] = defaultdict(float)
    doc_hits: dict[int, int] = defaultdict(int)
    for chunk in chunks:
        dist = getattr(chunk, "distance", None)
        if dist is not None:
            sim = max(0.0, 1.0 - float(dist))
        else:
            sim = 0.5
        doc_scores[chunk.document_id] += sim
        doc_hits[chunk.document_id] += 1

    ranked_ids = sorted(
        doc_scores.keys(),
        key=lambda did: (doc_scores[did], doc_hits[did]),
        reverse=True,
    )[:top_n]

    rows = list(Document.objects.filter(id__in=ranked_ids).values("id", "slug", "name"))
    by_id = {r["id"]: r for r in rows}
    out: list[dict] = []
    for did in ranked_ids:
        row = by_id.get(did)
        if not row:
            continue
        raw = doc_scores[did]
        relevance_score = min(100, round(20.0 * raw + 5 * doc_hits[did]))
        out.append(
            {
                "id": row["id"],
                "slug": row["slug"],
                "name": row["name"],
                "relevance_score": max(1, relevance_score),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Legacy vector-first retriever (still used by the orchestrator and tests)
# ---------------------------------------------------------------------------


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
    Strategies:
      - ``global``: classic vector-only top-N over the whole pool.
      - ``hybrid_per_document``: ensures recall coverage by taking top-k per
        document, then reranks globally with per-document caps.
      - ``auto``: picks ``hybrid_per_document`` for broad/multi-doc questions and
        ``global`` otherwise.
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
        from apps.project.models import ProjectShare

        shared_project_ids = ProjectShare.objects.filter(user=user).values_list(
            "project_id", flat=True
        )
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

    resolved_strategy = retrieval_strategy
    if retrieval_strategy == "auto":
        if len(doc_ids) > 3 or is_general_query(query_text):
            resolved_strategy = "hybrid_per_document"
        else:
            resolved_strategy = "global"

    if resolved_strategy != "hybrid_per_document":
        return list(qs.top_similar(query_text, top_n=top_n))

    query_embedding = embed_text(query_text)
    if not query_embedding:
        return list(qs.top_similar(query_text, top_n=top_n))

    ranked_qs = qs.annotate(
        distance=CosineDistance("embedding", query_embedding)
    ).order_by("distance")

    # Phase 1: per-document recall coverage.
    candidates: list[SmartChunk] = []
    safe_k_per_doc = max(1, k_per_doc)
    for doc_id in doc_ids:
        doc_top = list(ranked_qs.filter(document_id=doc_id)[:safe_k_per_doc])
        candidates.extend(doc_top)

    if not candidates:
        return []

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

    return cap_per_document(
        merged,
        max_per_doc=max_chunks_per_doc,
        total_limit=total_limit,
    )


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


def _scope_qs_for_user(user, doc_ids: list) -> QuerySet[SmartChunk]:
    qs = SmartChunk.objects.filter(document_id__in=doc_ids).exclude(embedding__isnull=True)
    if user is not None and not getattr(user, "is_staff", False):
        from apps.project.models import ProjectShare

        shared_project_ids = ProjectShare.objects.filter(user=user).values_list(
            "project_id", flat=True
        )
        qs = qs.filter(
            Q(document__owner=user)
            | Q(document__is_public=True)
            | Q(document__shares__user=user)
            | Q(document__projects__id__in=shared_project_ids)
        ).distinct()
    return qs


def _fill_missing_documents(
    *,
    base_qs: QuerySet[SmartChunk],
    query_text: str,
    missing_doc_ids: list,
    existing_chunks: list[SmartChunk],
) -> list[SmartChunk]:
    """
    Coverage fallback: retrieve one best chunk for every document missing from
    the final context. This is intentionally simple and deterministic; for
    all-docs prompts, predictability is more important than pure top-k score.
    """
    if not missing_doc_ids:
        return existing_chunks

    try:
        query_embedding = embed_text(query_text)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Coverage fallback embedding failed: %s", exc)
        query_embedding = None

    filled = list(existing_chunks)
    for doc_id in missing_doc_ids:
        doc_qs = base_qs.filter(document_id=doc_id)
        if query_embedding:
            chunk = (
                doc_qs.annotate(distance=CosineDistance("embedding", query_embedding))
                .order_by("distance", "chunk_index")
                .first()
            )
        else:
            chunk = doc_qs.order_by("chunk_index").first()
        if chunk is not None:
            filled.append(chunk)
    return filled


def retrieve_for_chat(
    *,
    user,
    query_text: str,
    allowed_documents: QuerySet[Document],
    top_n: int | None = None,
    total_limit: int | None = None,
    max_chunks_per_doc: int | None = None,
    k_per_doc: int = 2,
    topics: list[str] | None = None,
    response_mode: str | None = None,
) -> RetrievalResult:
    """
    Full RAG retrieval pipeline:

    1. Classify and (optionally) decompose the query.
    2. Run vector retrieval (per sub-query) via ``fetch_relevant_chunks``.
    3. Run lexical (trigram) retrieval over the same scope.
    4. Fuse with Reciprocal Rank Fusion (RRF).
    5. Optionally LLM-rerank the top-N pool.
    6. Apply per-document cap and (optionally) MMR diversity.
    7. Build a citation-ready context block.

    Returns a ``RetrievalResult`` with chunks, context, query analysis and
    diagnostics suitable for logging/observability.
    """
    started = time.perf_counter()
    diagnostics: dict = {
        "vector_candidates": 0,
        "lexical_candidates": 0,
        "fused_candidates": 0,
        "reranked": False,
        "mmr_applied": False,
        "sub_queries": 0,
        "documents_in_scope": 0,
        "coverage_mode": "focused",
        "coverage_target_ratio": None,
        "coverage_target_documents": None,
        "coverage_missing_documents": [],
        "coverage_met": True,
        "elapsed_seconds": 0.0,
    }

    if not query_text:
        return RetrievalResult(diagnostics=diagnostics)

    doc_ids = list(allowed_documents.values_list("id", flat=True))
    diagnostics["documents_in_scope"] = len(doc_ids)
    if not doc_ids:
        diagnostics["elapsed_seconds"] = time.perf_counter() - started
        return RetrievalResult(diagnostics=diagnostics)

    analysis = classify_query_hybrid(query_text)
    analysis = apply_response_mode_override(analysis, response_mode)
    queries = build_query_set(analysis)
    diagnostics["query_type"] = analysis.query_type
    diagnostics["coverage_mode"] = analysis.coverage_mode
    diagnostics["response_mode_override"] = response_mode or None
    diagnostics["classifier_source"] = analysis.classifier_source
    diagnostics["classifier_confidence"] = analysis.classifier_confidence
    diagnostics["sub_queries"] = max(0, len(queries) - 1)

    requires_all_docs = analysis.coverage_mode == COVERAGE_MODE_ALL
    coverage_target_ratio = RAG_ALL_DOCS_MIN_COVERAGE_RATIO if requires_all_docs else None
    diagnostics["coverage_target_ratio"] = coverage_target_ratio

    # Sizing the candidate pools.
    base_top_n = top_n or MAX_CONTEXT_CHUNKS
    multi_doc = len(doc_ids) > 1
    if requires_all_docs and multi_doc:
        # Coverage mode makes sense only with multiple documents: ensure at
        # least one chunk per document.  For single-document sessions we keep
        # the caller-supplied limits so "give me a summary" still retrieves
        # enough chunks instead of being hard-capped to 1.
        base_top_n = max(base_top_n, len(doc_ids))
        total_limit = max(total_limit or base_top_n, len(doc_ids))
        max_chunks_per_doc = 1
    pool_top_n = max(base_top_n, RAG_RERANK_POOL)
    vector_per_query = max(
        base_top_n,
        int(round(base_top_n * RAG_VECTOR_POOL_MULTIPLIER)),
    )
    lexical_per_query = max(
        base_top_n,
        int(round(base_top_n * RAG_LEXICAL_POOL_MULTIPLIER)),
    )

    # Strategy: panorama/comparative -> hybrid_per_document; else auto.
    vector_strategy = (
        "hybrid_per_document"
        if (requires_all_docs and multi_doc) or analysis.query_type == QUERY_TYPE_PANORAMA or len(doc_ids) > 3
        else "auto"
    )

    # --- Vector retrieval (per sub-query) ---
    vector_lists: list[list[SmartChunk]] = []
    for q in queries:
        try:
            vector_total_limit = len(doc_ids) if (requires_all_docs and multi_doc) else vector_per_query
            vector_k_per_doc = 1 if (requires_all_docs and multi_doc) else k_per_doc
            vector_max_per_doc = 1 if (requires_all_docs and multi_doc) else max(2, k_per_doc + 1)
            v_chunks = fetch_relevant_chunks(
                user=user,
                query_text=q,
                allowed_documents=allowed_documents,
                top_n=vector_per_query,
                topics=topics,
                retrieval_strategy=vector_strategy,
                k_per_doc=vector_k_per_doc,
                total_limit=vector_total_limit,
                max_chunks_per_doc=vector_max_per_doc,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Vector retrieval failed for sub-query %r: %s", q, exc)
            v_chunks = []
        if v_chunks:
            vector_lists.append(v_chunks)
            diagnostics["vector_candidates"] += len(v_chunks)

    # --- Lexical retrieval (single pass on original query) ---
    base_qs = _scope_qs_for_user(user, doc_ids)
    try:
        lex_chunks = lexical_search(base_qs, query_text, top_n=lexical_per_query)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Lexical retrieval failed: %s", exc)
        lex_chunks = []
    diagnostics["lexical_candidates"] = len(lex_chunks)

    # --- Fusion ---
    ranked_lists: list[list[SmartChunk]] = []
    ranked_lists.extend(vector_lists)
    if lex_chunks:
        ranked_lists.append(lex_chunks)

    if not ranked_lists:
        diagnostics["elapsed_seconds"] = time.perf_counter() - started
        return RetrievalResult(analysis=analysis, diagnostics=diagnostics)

    fused = rrf_fuse(ranked_lists, top_n=pool_top_n)
    diagnostics["fused_candidates"] = len(fused)

    # --- Optional LLM rerank ---
    safe_total = total_limit or base_top_n
    if is_reranker_enabled() and len(fused) > safe_total:
        fused = llm_rerank(query_text, fused, top_k=min(len(fused), pool_top_n))
        diagnostics["reranked"] = True

    # --- Diversity / per-doc cap ---
    safe_per_doc = max_chunks_per_doc if max_chunks_per_doc else max(1, min(3, k_per_doc + 1))
    capped = cap_per_document(
        fused,
        max_per_doc=safe_per_doc,
        total_limit=safe_total,
    )

    if requires_all_docs and multi_doc:
        covered_ids = {c.document_id for c in capped}
        target_count = max(1, int(round(len(doc_ids) * RAG_ALL_DOCS_MIN_COVERAGE_RATIO)))
        missing_doc_ids = [doc_id for doc_id in doc_ids if doc_id not in covered_ids]
        diagnostics["coverage_target_documents"] = target_count
        if len(covered_ids) < target_count and missing_doc_ids:
            capped = _fill_missing_documents(
                base_qs=base_qs,
                query_text=query_text,
                missing_doc_ids=missing_doc_ids,
                existing_chunks=capped,
            )
            capped = cap_per_document(
                capped,
                max_per_doc=1,
                total_limit=max(safe_total, target_count),
            )

    # --- Optional MMR (off by default) ---
    final_chunks: list[SmartChunk] = capped
    if is_mmr_enabled() and capped:
        try:
            q_emb = embed_text(query_text)
            final_chunks = mmr_select(capped, q_emb, top_k=safe_total)
            diagnostics["mmr_applied"] = True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("MMR selection failed, falling back to capped: %s", exc)
            final_chunks = capped

    context_block = _build_context_block(final_chunks, with_citations=True)

    diagnostics["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    diagnostics["final_chunks"] = len(final_chunks)
    diagnostics["unique_documents"] = len({c.document_id for c in final_chunks})
    final_doc_ids = {c.document_id for c in final_chunks}
    missing_doc_ids = [doc_id for doc_id in doc_ids if doc_id not in final_doc_ids]
    diagnostics["coverage_missing_documents"] = missing_doc_ids
    if requires_all_docs:
        target_count = diagnostics["coverage_target_documents"] or len(doc_ids)
        diagnostics["coverage_met"] = len(final_doc_ids) >= target_count

    return RetrievalResult(
        chunks=final_chunks,
        context_block=context_block,
        analysis=analysis,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Backward-compatible re-exports
# ---------------------------------------------------------------------------


def build_context_block(chunks: Iterable[SmartChunk]) -> str:
    """Backward-compatible wrapper. New callers should use the orchestrator."""
    return _build_context_block(chunks, with_citations=True)


__all__ = [
    "MAX_CONTEXT_CHUNKS",
    "RetrievalResult",
    "build_citation_prompt",
    "build_context_block",
    "fetch_relevant_chunks",
    "is_general_query",
    "retrieve_for_chat",
    "suggest_related_library_documents",
]
