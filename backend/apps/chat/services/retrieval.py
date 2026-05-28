"""
Hybrid retrieval helpers (lexical + RRF fusion) for the RAG pipeline.

Vector retrieval is intentionally delegated to ``apps.chat.services.rag.fetch_relevant_chunks``
to keep a single source of truth and preserve mock-friendliness in tests.

Lexical retrieval uses Postgres trigram similarity over the ``content_norm``
generated column (already created in migration 0003). Falls back to a Python
ICONTAINS match when trigram is unavailable (e.g. unit tests on stripped DBs).

Fusion uses Reciprocal Rank Fusion (RRF), which is robust to score scales.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable, List, Sequence

from django.db.models import Q, QuerySet

from apps.document.models import SmartChunk

logger = logging.getLogger(__name__)


RRF_K = int(os.environ.get("RAG_RRF_K", "60"))
LEXICAL_TOP_N = int(os.environ.get("RAG_LEXICAL_TOP_N", "20"))
LEXICAL_MIN_SIMILARITY = float(os.environ.get("RAG_LEXICAL_MIN_SIMILARITY", "0.05"))


def _normalize_for_lexical(text: str) -> str:
    """Approximate the immutable_unaccent(lower(...)) generated column."""
    if not text:
        return ""
    text = text.lower()
    # Light unaccenting that handles Spanish diacritics; the DB does the heavy
    # lifting via the unaccent extension when trigram is used.
    repl = str.maketrans({
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ä": "a", "ë": "e", "ï": "i", "ö": "o", "ü": "u",
        "ñ": "n",
    })
    return text.translate(repl)


def _query_tokens(text: str, *, min_len: int = 3, limit: int = 8) -> List[str]:
    norm = _normalize_for_lexical(text)
    tokens = [t for t in re.findall(r"[a-z0-9]+", norm) if len(t) >= min_len]
    seen: set[str] = set()
    out: List[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def lexical_search(
    base_qs: QuerySet[SmartChunk],
    query_text: str,
    *,
    top_n: int = LEXICAL_TOP_N,
) -> List[SmartChunk]:
    """
    Trigram-based lexical retrieval over content_norm.
    Returns up to ``top_n`` SmartChunk instances ordered by similarity desc.
    """
    if not query_text:
        return []

    norm_query = _normalize_for_lexical(query_text)
    if not norm_query:
        return []

    # Try Postgres trigram similarity first (depends on pg_trgm).
    try:
        from django.contrib.postgres.search import TrigramSimilarity

        qs = (
            base_qs.annotate(lex_sim=TrigramSimilarity("content_norm", norm_query))
            .filter(lex_sim__gt=LEXICAL_MIN_SIMILARITY)
            .order_by("-lex_sim")[: top_n]
        )
        return list(qs)
    except Exception as exc:  # pragma: no cover - defensive (no pg_trgm, sqlite, etc.)
        logger.info("TrigramSimilarity unavailable, falling back to icontains: %s", exc)

    # Fallback: token-based icontains scoring (slower but portable).
    tokens = _query_tokens(query_text)
    if not tokens:
        return []
    or_filter = Q()
    for t in tokens:
        or_filter |= Q(content_norm__icontains=t)
    candidates = list(base_qs.filter(or_filter).only("id", "content_norm", "document_id")[:200])

    n_tokens = len(tokens)

    def _lex_score(chunk: SmartChunk) -> float:
        text = (chunk.content_norm or "").lower()
        hits = sum(1 for t in tokens if t in text)
        return hits / n_tokens

    # Annotate lex_sim so _chunk_similarity() in the pipeline can evaluate these
    # chunks against RAG_MIN_SIMILARITY, matching the behaviour of the trigram path.
    for c in candidates:
        c.lex_sim = _lex_score(c)  # type: ignore[attr-defined]
    candidates = [c for c in candidates if c.lex_sim >= LEXICAL_MIN_SIMILARITY]
    candidates.sort(key=lambda c: c.lex_sim, reverse=True)  # type: ignore[attr-defined]
    return candidates[:top_n]


def rrf_fuse(
    ranked_lists: Sequence[Sequence[SmartChunk]],
    *,
    k: int = RRF_K,
    top_n: int | None = None,
) -> List[SmartChunk]:
    """
    Reciprocal Rank Fusion over multiple ranked lists of SmartChunk.

    Score = sum_i 1 / (k + rank_i(c)). Higher is better.
    Returns up to ``top_n`` chunks (or all fused) sorted by aggregate score.
    """
    scores: dict[int, float] = {}
    keep: dict[int, SmartChunk] = {}

    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            cid = getattr(chunk, "id", None)
            if cid is None:
                continue
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            keep.setdefault(cid, chunk)

    fused = sorted(keep.values(), key=lambda c: scores.get(c.id, 0.0), reverse=True)
    if top_n is not None:
        fused = fused[: max(0, top_n)]
    # Stash the score on each chunk as an attribute for downstream debugging.
    for c in fused:
        try:
            setattr(c, "rrf_score", scores.get(c.id, 0.0))
        except Exception:
            pass
    return fused


def cap_per_document(
    chunks: Iterable[SmartChunk],
    *,
    max_per_doc: int,
    total_limit: int,
) -> List[SmartChunk]:
    """Apply per-document cap and total limit while preserving order."""
    selected: List[SmartChunk] = []
    counters: dict = {}
    safe_per_doc = max(1, max_per_doc)
    safe_total = max(1, total_limit)
    for chunk in chunks:
        used = counters.get(chunk.document_id, 0)
        if used >= safe_per_doc:
            continue
        selected.append(chunk)
        counters[chunk.document_id] = used + 1
        if len(selected) >= safe_total:
            break
    return selected
