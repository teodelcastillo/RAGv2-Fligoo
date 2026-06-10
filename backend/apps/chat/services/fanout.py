"""
Per-document fan-out (map-reduce) for per-entity extraction — Phase 4.

The task "extraé X de cada documento" (``extract_per_entity``) is structurally a
map-reduce, not a single shared-context pass: each document must be read and
answered on its own, then the per-document answers consolidated. Doing it as one
retrieval over a shared budget is what made the engine conflate which value
belongs to which document.

This module is the executor for that pattern. It is triggered by the shared
retrieval plan (``plan.per_document_answer`` — set by the Phase 3 router for
multi-document per-entity queries). It reuses the existing retrieval pipeline
(``retrieve_for_chat`` per document, so F1 recall + parent expansion apply) and
the provider-agnostic generation layer (F2 tiers — the per-document *map* runs on
the FAST tier, i.e. Haiku when ``LLM_PROVIDER=anthropic``).

Citations stay globally consistent: each document's local ``[#N]`` indices are
shifted by that document's offset into a single global chunk list, so the
existing ``_extract_citation_payload`` resolves them unchanged.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[#(\d+)\]")

_MAP_SYSTEM_PROMPT = (
    "Sos un analista experto en ESG, clima y biodiversidad. Extraé del siguiente "
    "documento ÚNICAMENTE la información que pide el usuario, de forma breve y "
    "concreta (el dato/campo pedido, no un resumen). "
    "Si el documento NO contiene esa información, respondé EXACTAMENTE: "
    "'No especificado en este documento.' "
    "Citá con [#N] el fragmento del que surge el dato; no cites si no hay dato."
)

_NOT_FOUND_MARKER = "no especificado en este documento"


def _fanout_enabled() -> bool:
    return os.environ.get("RAG_FANOUT_ENABLED", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _max_docs() -> int:
    try:
        return int(os.environ.get("RAG_FANOUT_MAX_DOCS", "20"))
    except ValueError:
        return 20


def _per_doc_top_n() -> int:
    try:
        return int(os.environ.get("RAG_FANOUT_PER_DOC_TOP_N", "4"))
    except ValueError:
        return 4


@dataclass
class FanoutDocResult:
    document_id: int
    document_name: str
    document_slug: str
    answer: str               # per-document extraction (citations already global)
    found: bool
    chunk_ids: List[int] = field(default_factory=list)


@dataclass
class FanoutResult:
    answer: str               # consolidated final text (global [#N] citations)
    per_document: List[FanoutDocResult] = field(default_factory=list)
    chunks: list = field(default_factory=list)   # global ordered SmartChunk list
    usage: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)


def should_fanout(retrieval) -> bool:
    """True when the retrieval plan asks for a per-document answer."""
    if retrieval is None:
        return False
    plan = (retrieval.diagnostics or {}).get("retrieval_plan") or {}
    return bool(plan.get("per_document_answer"))


def _shift_citations(text: str, offset: int) -> str:
    if offset <= 0 or not text:
        return text or ""
    return _CITATION_RE.sub(lambda m: f"[#{int(m.group(1)) + offset}]", text)


def run_per_document_extraction(
    *,
    user,
    query_text: str,
    allowed_documents,
    response_mode: str | None = None,
    map_model: str | None = None,
) -> FanoutResult:
    """Map each in-scope document → per-document extraction, then reduce.

    Returns a FanoutResult whose ``answer`` cites a single global chunk list so
    the existing citation pipeline works unchanged.
    """
    # Imported here to avoid import cycles (rag imports nothing from fanout).
    from apps.chat.services.context_builder import build_context_block
    from apps.chat.services.rag import retrieve_for_chat
    from apps.document.utils.client_openia import generate_chat_completion
    from apps.document.utils.llm import ROLE_FAST, resolve_model

    docs = list(allowed_documents[: _max_docs()])
    map_model = map_model or os.environ.get("RAG_FANOUT_MAP_MODEL") or resolve_model(ROLE_FAST)

    global_chunks: list = []
    per_doc: list[FanoutDocResult] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    per_doc_top_n = _per_doc_top_n()

    for doc in docs:
        single_qs = allowed_documents.filter(id=doc.id)
        try:
            result = retrieve_for_chat(
                user=user,
                query_text=query_text,
                allowed_documents=single_qs,
                response_mode=response_mode,
                top_n=per_doc_top_n,
                total_limit=per_doc_top_n,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Fanout retrieval failed for doc %s: %s", doc.id, exc)
            result = None

        doc_chunks = list(result.chunks) if result else []
        offset = len(global_chunks)

        if doc_chunks:
            context_block = build_context_block(doc_chunks, with_citations=True)
            try:
                local_text, doc_usage = generate_chat_completion(
                    [
                        {"role": "system", "content": _MAP_SYSTEM_PROMPT},
                        {"role": "system", "content": "Contexto del documento:\n\n" + context_block},
                        {"role": "user", "content": query_text},
                    ],
                    model=map_model,
                    temperature=0.0,
                    max_tokens=int(os.environ.get("RAG_FANOUT_MAP_MAX_TOKENS", "350")),
                    timeout=60,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Fanout map generation failed for doc %s: %s", doc.id, exc)
                local_text, doc_usage = "No especificado en este documento.", {}
            for k in usage:
                usage[k] += (doc_usage or {}).get(k, 0)
        else:
            local_text = "No especificado en este documento."

        answer = _shift_citations(local_text.strip(), offset)
        global_chunks.extend(doc_chunks)
        found = _NOT_FOUND_MARKER not in local_text.strip().lower()

        per_doc.append(
            FanoutDocResult(
                document_id=doc.id,
                document_name=getattr(doc, "name", "") or getattr(doc, "slug", "") or str(doc.id),
                document_slug=getattr(doc, "slug", "") or "",
                answer=answer,
                found=found,
                chunk_ids=[c.id for c in doc_chunks],
            )
        )

    final_answer = _reduce(per_doc)
    diagnostics = {
        "fanout": True,
        "fanout_documents": len(per_doc),
        "fanout_documents_found": sum(1 for r in per_doc if r.found),
        "fanout_chunks": len(global_chunks),
        "fanout_map_model": map_model,
    }
    return FanoutResult(
        answer=final_answer,
        per_document=per_doc,
        chunks=global_chunks,
        usage=usage,
        diagnostics=diagnostics,
    )


def _reduce(per_doc: List[FanoutDocResult]) -> str:
    """Deterministic consolidation: one line per document, citations preserved."""
    if not per_doc:
        return "No se encontraron documentos en alcance para esta consulta."
    lines = [f"- **{r.document_name}**: {r.answer}" for r in per_doc]
    return "\n".join(lines)


def maybe_fanout(
    retrieval,
    *,
    user,
    query_text: str,
    allowed_documents,
    response_mode: str | None = None,
) -> Optional[FanoutResult]:
    """Run the fan-out if the plan asks for it and there are multiple documents.

    Returns ``None`` when fan-out does not apply or is disabled, so the caller
    falls back to the normal single-pass generation.
    """
    if not _fanout_enabled() or not should_fanout(retrieval):
        return None
    try:
        if allowed_documents is None or allowed_documents.count() < 2:
            return None
    except Exception:  # pragma: no cover - defensive (non-queryset)
        return None
    try:
        return run_per_document_extraction(
            user=user,
            query_text=query_text,
            allowed_documents=allowed_documents,
            response_mode=response_mode,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Fan-out failed, falling back to single-pass: %s", exc)
        return None


def apply_fanout(retrieval, fanout_result: FanoutResult):
    """Fold a FanoutResult into the RetrievalResult so the existing citation and
    metadata pipeline (``_extract_citation_payload``) works unchanged.

    Replaces the retrieval chunks with the global fan-out chunk list (which the
    final answer's ``[#N]`` indices point at) and merges diagnostics.
    """
    retrieval.chunks = list(fanout_result.chunks)
    retrieval.context_block = ""  # already consumed by the per-document maps
    if retrieval.diagnostics is None:
        retrieval.diagnostics = {}
    retrieval.diagnostics.update(fanout_result.diagnostics)
    return retrieval
