"""
LLM-based listwise reranker for the RAG pipeline.

Wraps a single chat call that takes the user's query plus N candidate excerpts
and returns the top-K indices in order of relevance. Always defensive: falls
back to identity ordering on any error so the pipeline never breaks.

Disabled by default; opt-in via RAG_RERANKER_ENABLED=1 to control cost.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Sequence

from apps.document.models import SmartChunk

logger = logging.getLogger(__name__)


def is_reranker_enabled() -> bool:
    return os.environ.get("RAG_RERANKER_ENABLED", "0").lower() in (
        "1", "true", "yes", "on",
    )


def _excerpt(text: str, max_chars: int = 600) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def llm_rerank(
    query: str,
    candidates: Sequence[SmartChunk],
    *,
    top_k: int,
    model: str | None = None,
) -> List[SmartChunk]:
    """
    Rerank ``candidates`` for ``query`` using a single LLM call.
    Returns at most ``top_k`` chunks ordered by relevance.
    On any failure, returns the first ``top_k`` of the input unchanged.
    """
    if not candidates or top_k <= 0:
        return list(candidates[:top_k])
    if not is_reranker_enabled():
        return list(candidates[:top_k])

    try:
        from apps.document.utils.client_openia import generate_chat_completion

        listing = []
        for i, chunk in enumerate(candidates, start=1):
            doc_name = getattr(getattr(chunk, "document", None), "name", "") or "doc"
            listing.append(f"[{i}] ({doc_name}) {_excerpt(chunk.content)}")

        system = (
            "Eres un reranker de pasajes para un sistema RAG. Recibes una "
            "pregunta y una lista numerada de fragmentos. Devuelve EXCLUSIVAMENTE "
            "un JSON array con los índices (1-based) de los fragmentos más "
            "relevantes, en orden decreciente de relevancia, con un máximo de "
            f"{top_k}. No incluyas explicación. Si ningún fragmento es relevante, "
            "devuelve un subconjunto pequeño y razonable, no un array vacío."
        )
        user = (
            f"Pregunta: {query}\n\n"
            f"Fragmentos ({len(listing)}):\n" + "\n".join(listing)
        )
        text, _ = generate_chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model or os.environ.get("RAG_RERANKER_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=120,
            timeout=20,
        )
        match = re.search(r"\[[\s\S]*\]", text or "")
        if not match:
            raise ValueError(f"reranker did not return JSON: {text!r}")
        raw = json.loads(match.group(0))
        if not isinstance(raw, list):
            raise ValueError("reranker JSON is not a list")

        order: List[int] = []
        seen: set[int] = set()
        for item in raw:
            try:
                idx = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= len(candidates) and idx not in seen:
                seen.add(idx)
                order.append(idx)
            if len(order) >= top_k:
                break

        if not order:
            return list(candidates[:top_k])

        ordered = [candidates[i - 1] for i in order]
        # Fill remaining slots with leftover candidates preserving their order.
        if len(ordered) < top_k:
            for i, c in enumerate(candidates, start=1):
                if i in seen:
                    continue
                ordered.append(c)
                if len(ordered) >= top_k:
                    break
        return ordered[:top_k]

    except Exception as exc:
        logger.warning("LLM rerank failed, returning original order: %s", exc)
        return list(candidates[:top_k])
