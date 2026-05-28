"""
Context construction for the RAG pipeline.

Provides:
- ``build_context_block``: citation-friendly context with [#N] indices.
- ``mmr_select``: optional diversity selection over the final candidates.
- Helpers for citation prompts that the chat layer reuses.

Citations are encoded as ``[#1]``, ``[#2]``, ... matching the order of the
chunks list passed to the prompt; the same chunks are persisted on the
``ChatMessage.chunk_ids`` array so the frontend can resolve sources.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Iterable, List, Sequence

from apps.document.models import SmartChunk

logger = logging.getLogger(__name__)


CITATION_INSTRUCTIONS = (
    "Reglas de citación:\n"
    "- Cita inline con [#N] cada afirmación factual que provenga de un fragmento del contexto.\n"
    "- Solo adjuntá [#N] si ese fragmento contiene EXPLÍCITAMENTE el dato que afirmás. "
    "No cites un fragmento porque sea temáticamente similar o habla del mismo tema general.\n"
    "- Si usás conocimiento propio (no documental), escribí [información general] "
    "en esa afirmación en lugar de [#N]. Nunca adjuntes un [#N] a datos de tu entrenamiento.\n"
    "- Si la información sobre un país, entidad o hecho específico no está en el contexto, "
    "declaralo explícitamente: 'No encontré evidencia documental sobre [X].' "
    "No lo rellenes con conocimiento general sin marcarlo."
)

# Variant for PANORAMA / COMPARATIVE queries where the task is to *synthesize*
# across many fragments rather than look for a pre-compiled answer in a single one.
PANORAMA_CITATION_INSTRUCTIONS = (
    "Reglas de citación para respuesta de panorama regional:\n"
    "- Cita inline con [#N] cada dato que extraigas de un fragmento.\n"
    "- Solo adjuntá [#N] si ese fragmento contiene explícitamente el dato citado.\n"
    "- Si usás conocimiento propio, escribí [información general] en esa afirmación "
    "y nunca le adjuntés un [#N].\n"
    "- Tu tarea es COMPILAR y SINTETIZAR lo que cada fragmento dice: "
    "NO escribas 'No encontré evidencia documental' cuando hay fragmentos en el contexto. "
    "Si un fragmento cubre un país pero no incluye el dato específico pedido, "
    "anotá 'dato no especificado en el fragmento recuperado' para ese país, "
    "y seguí con los demás países.\n"
    "- No omitas ningún país que tenga fragmento en el contexto, aunque el fragmento "
    "sea parcial o no responda directamente la pregunta."
)


def build_context_block(
    chunks: Iterable[SmartChunk],
    *,
    with_citations: bool = True,
    max_chars_per_chunk: int | None = None,
) -> str:
    """
    Build the context string injected into the LLM prompt.
    When ``with_citations`` is True (default), each fragment is prefixed with
    ``[#N]`` so the model can produce inline citations the UI can resolve.
    """
    sections: List[str] = []
    for index, chunk in enumerate(chunks, start=1):
        content = (chunk.content or "").strip()
        if max_chars_per_chunk and len(content) > max_chars_per_chunk:
            content = content[: max_chars_per_chunk - 1].rstrip() + "…"
        document = getattr(chunk, "document", None)
        doc_name = getattr(document, "name", "") or "documento"
        doc_slug = getattr(document, "slug", "") or ""
        header = (
            f"[#{index}] Fuente: {doc_name}"
            if with_citations
            else f"Fuente: {doc_name}"
        )
        if doc_slug:
            header += f" (slug: {doc_slug}, chunk #{chunk.chunk_index})"
        chunk_title = (getattr(chunk, "title", "") or "").strip()
        if chunk_title:
            header += f" | Sección: {chunk_title}"
        ctx = (getattr(chunk, "context_summary", "") or "").strip()
        body = f"Contexto: {ctx}\n{content}" if ctx else content
        sections.append(f"{header}\n{body}")
    return "\n\n".join(sections).strip()


def build_citation_prompt(query_type: str | None = None) -> str:
    """Return the system snippet that instructs the LLM to cite sources.

    For PANORAMA / COMPARATIVE queries, returns a synthesis-oriented variant
    that tells the model to compile across fragments rather than look for a
    pre-compiled list.
    """
    if query_type in {"panorama", "comparative"}:
        return PANORAMA_CITATION_INSTRUCTIONS
    return CITATION_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Optional MMR-like diversity (off by default)
# ---------------------------------------------------------------------------

def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def mmr_select(
    candidates: Sequence[SmartChunk],
    query_embedding: Sequence[float] | None,
    *,
    top_k: int,
    lambda_: float = 0.7,
) -> List[SmartChunk]:
    """
    Maximal Marginal Relevance over candidates.
    Falls back to the input order if any embedding is missing.
    """
    if top_k <= 0 or not candidates:
        return []
    if not query_embedding:
        return list(candidates[:top_k])

    pool = list(candidates)
    selected: List[SmartChunk] = []

    def emb(chunk: SmartChunk) -> Sequence[float] | None:
        e = getattr(chunk, "embedding", None)
        if e is None:
            return None
        try:
            return list(e)
        except TypeError:
            return None

    sims_to_query: dict[int, float] = {}
    for c in pool:
        e = emb(c)
        sims_to_query[c.id] = _cosine(query_embedding, e) if e else 0.0

    while pool and len(selected) < top_k:
        best = None
        best_score = -math.inf
        for cand in pool:
            sim_q = sims_to_query.get(cand.id, 0.0)
            cand_emb = emb(cand)
            if not selected or cand_emb is None:
                diversity = 0.0
            else:
                diversity = max(
                    _cosine(cand_emb, emb(s) or []) for s in selected
                )
            score = lambda_ * sim_q - (1.0 - lambda_) * diversity
            if score > best_score:
                best_score = score
                best = cand
        if best is None:
            break
        selected.append(best)
        pool.remove(best)
    return selected


def is_mmr_enabled() -> bool:
    return os.environ.get("RAG_MMR_ENABLED", "0").lower() in (
        "1", "true", "yes", "on",
    )
