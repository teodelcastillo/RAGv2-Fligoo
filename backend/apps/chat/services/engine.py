"""
Unified answer engine — the single orchestrator (Phase 5).

After Phases 1-4 the three stacks already share the building blocks:
- retrieval        → ``retrieve_for_chat`` (recall + parent expansion + the plan)
- per-document map → ``fanout`` (extract_per_entity)
- generation       → ``generate_chat_completion`` (provider-agnostic / Claude tiers)
- routing          → ``query_analysis`` (the plan / strategy brain)

This module ties them into ONE entry point — ``run_engine`` — that takes a
query over a document scope and returns a cited answer plus full telemetry. It
is the public "answer a question over documents" primitive that new consumers
(and the per-client configuration layer in Phase 6) target, instead of
re-wiring retrieve → (fanout | generate) → citations by hand.

Chat keeps its own session-coupled orchestration (history rewrite, library
fallback, streaming, recommendations) on top of these same shared pieces; the
engine does not try to absorb that domain logic — it unifies the common core.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from apps.chat.services.context_builder import build_citation_prompt
from apps.chat.services.fanout import apply_fanout, maybe_fanout
from apps.chat.services.rag import retrieve_for_chat

_DEFAULT_SYSTEM_PROMPT = (
    "Eres Ecofilia, un asistente experto en ESG, cambio climático y biodiversidad. "
    "Respondé usando EXCLUSIVAMENTE la información de los fragmentos de contexto "
    "provistos. Sé preciso y conciso. Si el dato pedido no está en los fragmentos, "
    "declaralo explícitamente en lugar de inventarlo."
)

_NO_CONTEXT_NOTE = (
    "No se recuperó ningún fragmento de contexto para esta consulta. "
    "Si no podés responder con evidencia documental, declaralo explícitamente."
)


@dataclass
class EngineRequest:
    user: object
    query: str
    documents: object                       # QuerySet[Document] (the scope)
    system_prompt: Optional[str] = None
    response_mode: Optional[str] = None
    retrieval_strategy: Optional[str] = None  # explicit override (skills/eval)
    model: Optional[str] = None
    temperature: float = 0.1
    max_tokens: Optional[int] = None
    top_n: Optional[int] = None
    total_limit: Optional[int] = None
    enable_fanout: bool = True


@dataclass
class EngineResult:
    answer: str
    chunks: list = field(default_factory=list)
    context_block: str = ""
    analysis: object = None
    plan: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    fanout: bool = False


def run_engine(req: EngineRequest) -> EngineResult:
    """Retrieve → (per-document fan-out | single-pass generation) → cited answer."""
    retrieval = retrieve_for_chat(
        user=req.user,
        query_text=req.query,
        allowed_documents=req.documents,
        response_mode=req.response_mode,
        retrieval_strategy=req.retrieval_strategy,
        top_n=req.top_n,
        total_limit=req.total_limit,
    )
    plan = (retrieval.diagnostics or {}).get("retrieval_plan", {})

    # Per-document map-reduce (extract_per_entity) when the plan asks for it.
    if req.enable_fanout:
        fanout_result = maybe_fanout(
            retrieval,
            user=req.user,
            query_text=req.query,
            allowed_documents=req.documents,
            response_mode=req.response_mode,
        )
        if fanout_result is not None:
            apply_fanout(retrieval, fanout_result)
            return EngineResult(
                answer=fanout_result.answer,
                chunks=list(retrieval.chunks),
                context_block="",
                analysis=retrieval.analysis,
                plan=plan,
                usage=fanout_result.usage,
                diagnostics=retrieval.diagnostics or {},
                fanout=True,
            )

    answer, usage = _generate(req, retrieval)
    return EngineResult(
        answer=answer,
        chunks=list(retrieval.chunks),
        context_block=retrieval.context_block,
        analysis=retrieval.analysis,
        plan=plan,
        usage=usage,
        diagnostics=retrieval.diagnostics or {},
        fanout=False,
    )


def _generate(req: EngineRequest, retrieval) -> tuple[str, dict]:
    from apps.document.utils.client_openia import generate_chat_completion

    query_type = (
        getattr(retrieval.analysis, "query_type", None) if retrieval.analysis else None
    )
    system_text = (
        (req.system_prompt or _DEFAULT_SYSTEM_PROMPT)
        + "\n\n"
        + build_citation_prompt(query_type)
    )
    messages = [{"role": "system", "content": system_text}]
    if retrieval.context_block:
        messages.append(
            {"role": "system", "content": "Contexto documental:\n\n" + retrieval.context_block}
        )
    else:
        messages.append({"role": "system", "content": _NO_CONTEXT_NOTE})
    messages.append({"role": "user", "content": req.query})

    max_tokens = req.max_tokens or int(os.environ.get("ENGINE_ANSWER_MAX_TOKENS", "700"))
    text, usage = generate_chat_completion(
        messages,
        model=req.model,
        temperature=req.temperature,
        max_tokens=max_tokens,
        timeout=90,
    )
    return (text or "").strip(), (usage or {})
