"""
Phase 0 — Quality & coverage evaluation harness for the RAG pipeline.

This module *layers* on top of the existing retrieval-only harness
(``rag_evaluation.py``). Where that one measures whether the right chunks were
retrieved, this one also runs the **generation** step and scores the final
answer against known ground truth, on the three axes that matter for the
product:

1. Recall / completeness — if the data exists in scope, did the answer include
   it? Measured at two levels so we can tell *where* a miss happens:
     - ``retrieval_recall``: was the expected evidence retrieved at all?
     - ``answer_recall``:    did the final answer state the expected facts?
   The gap between the two localizes the failure (retrieval vs generation).

2. Provenance / traceability — did the answer cite, and do the cited ``[#N]``
   fragments map to the expected source location?

3. "Not present" vs "didn't look" — on negative cases (answer NOT in the
   corpus), did the model correctly abstain instead of fabricating? And, when
   context exists, is every claim in the answer supported by it (faithfulness)?

The harness runs against the **real** production path: it calls
``retrieve_for_chat`` and then a generation step that mirrors the chat layer's
prompt composition (same context block, same citation instructions). It never
reimplements retrieval.

LLM-as-judge is used for the semantic metrics (answer recall, abstention,
faithfulness). The judge degrades gracefully: if no API key is configured or a
call fails, those metrics are reported as ``None`` (skipped) and the
deterministic metrics (retrieval recall, citation mapping, latency) still run,
so the harness is usable fully offline for the retrieval layer.

Design notes:
- Dependency-free (no pytest/pandas) so it runs from a management command.
- Judge and answer prompts are versioned (``PROMPT_VERSION``) so a metric shift
  caused by a prompt edit is auditable.
- This is a dev/QA tool. It is intentionally separate from the ``evaluation``
  app, which is the ESG-scoring *product* feature.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, List, Optional

from django.db.models import QuerySet

from apps.chat.services.context_builder import build_citation_prompt
from apps.chat.services.engine import EngineRequest, run_engine
from apps.chat.services.fanout import run_per_document_extraction, should_fanout
from apps.chat.services.rag import RetrievalResult, retrieve_for_chat
from apps.chat.services.rag_evaluation import _coverage, _keyword_recall
from apps.document.models import Document

logger = logging.getLogger(__name__)

# Bump when the answer/judge prompts below change, so baselines remain
# comparable and a metric movement can be attributed to a prompt edit.
PROMPT_VERSION = "v1"

# Models. Default the *answer* model to the production completion model so the
# baseline reflects what users get today. The judge should ideally be a
# stronger model; override via env in CI.
_ANSWER_MODEL = os.environ.get("RAG_EVAL_ANSWER_MODEL")  # None -> MODEL_COMPLETION
_JUDGE_MODEL = os.environ.get("RAG_EVAL_JUDGE_MODEL")    # None -> MODEL_COMPLETION

_CITATION_RE = re.compile(r"\[#(\d+)\]")

VALID_TASK_TYPES = {
    "factual",
    "numeric",
    "extract_per_entity",
    "comparative",
    "panorama",
}


# ---------------------------------------------------------------------------
# Case + result schema
# ---------------------------------------------------------------------------


@dataclass
class QualityCase:
    """A single gold case. Superset of ``RagEvalCase`` (backward compatible)."""

    question: str
    id: str = ""
    task_type: str = "factual"
    scope: str = ""  # single_doc|few_docs|many_docs|repository (informational)
    expected_document_slugs: List[str] = field(default_factory=list)
    expected_facts: List[str] = field(default_factory=list)
    # Provenance ground truth: [{"document_slug": "...", "page": 14}, ...]
    expected_evidence: List[dict] = field(default_factory=list)
    answer_exists: bool = True
    expected_keywords: List[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, item: dict) -> "QualityCase":
        return cls(
            question=str(item.get("question", "")).strip(),
            id=str(item.get("id", "")).strip(),
            task_type=str(item.get("task_type", "factual")).strip().lower()
            or "factual",
            scope=str(item.get("scope", "")).strip(),
            expected_document_slugs=list(item.get("expected_document_slugs", [])),
            expected_facts=list(item.get("expected_facts", [])),
            expected_evidence=list(item.get("expected_evidence", [])),
            answer_exists=bool(item.get("answer_exists", True)),
            expected_keywords=list(item.get("expected_keywords", [])),
            notes=str(item.get("notes", "")),
        )


@dataclass
class QualityCaseResult:
    case: QualityCase
    # Retrieval layer (deterministic)
    retrieval_recall_docs: float          # expected docs present in retrieved
    retrieval_recall_pages: Optional[float]  # expected pages present (None if no page GT)
    keyword_recall: float
    num_chunks: int
    unique_sources: int
    # Answer layer
    answer: str
    answer_recall: Optional[float]        # LLM judge; None if skipped
    # Provenance
    cited_any: bool
    citation_correctness: Optional[float]  # fraction of [#N] mapping to expected docs
    expected_evidence_cited: Optional[bool]
    # Abstention / faithfulness
    abstained: Optional[bool]             # negative cases only
    fabricated: Optional[bool]            # negative cases only
    faithful: Optional[bool]              # positive-with-context only
    unsupported_claims: List[str] = field(default_factory=list)
    # Telemetry / trace
    latency_seconds: float = 0.0
    usage: dict = field(default_factory=dict)
    retrieved_slugs: List[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    error: str = ""
    # Routing (Phase 3): classifier prediction vs the case's declared task_type.
    routing_predicted: str = ""
    routing_correct: Optional[bool] = None

    def to_dict(self) -> dict:
        return {
            "id": self.case.id,
            "question": self.case.question,
            "task_type": self.case.task_type,
            "answer_exists": self.case.answer_exists,
            "metrics": {
                "retrieval_recall_docs": self.retrieval_recall_docs,
                "retrieval_recall_pages": self.retrieval_recall_pages,
                "keyword_recall": self.keyword_recall,
                "answer_recall": self.answer_recall,
                "cited_any": self.cited_any,
                "citation_correctness": self.citation_correctness,
                "expected_evidence_cited": self.expected_evidence_cited,
                "abstained": self.abstained,
                "fabricated": self.fabricated,
                "faithful": self.faithful,
                "routing_predicted": self.routing_predicted,
                "routing_correct": self.routing_correct,
            },
            "answer": self.answer,
            "unsupported_claims": self.unsupported_claims,
            "trace": {
                "num_chunks": self.num_chunks,
                "unique_sources": self.unique_sources,
                "retrieved_slugs": self.retrieved_slugs,
                "latency_seconds": round(self.latency_seconds, 3),
                "usage": self.usage,
                "diagnostics": self.diagnostics,
            },
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Aggregation / report
# ---------------------------------------------------------------------------


def _safe_mean(values: Iterable[Optional[float]]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(mean(nums), 3)


@dataclass
class QualityReport:
    results: List[QualityCaseResult] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION

    def aggregate(self) -> dict:
        rs = self.results
        positives = [r for r in rs if r.case.answer_exists]
        negatives = [r for r in rs if not r.case.answer_exists]
        return {
            "n": len(rs),
            "n_positive": len(positives),
            "n_negative": len(negatives),
            "prompt_version": self.prompt_version,
            # Recall
            "retrieval_recall_docs": _safe_mean(
                r.retrieval_recall_docs for r in positives
            ),
            "retrieval_recall_pages": _safe_mean(
                r.retrieval_recall_pages for r in positives
            ),
            "answer_recall": _safe_mean(r.answer_recall for r in positives),
            # Provenance
            "cited_any": _safe_mean(
                (1.0 if r.cited_any else 0.0) for r in positives
            ),
            "citation_correctness": _safe_mean(
                r.citation_correctness for r in positives
            ),
            "expected_evidence_cited": _safe_mean(
                (1.0 if r.expected_evidence_cited else 0.0)
                for r in positives
                if r.expected_evidence_cited is not None
            ),
            # Abstention (negatives) / faithfulness (positives)
            "abstention_rate": _safe_mean(
                (1.0 if r.abstained else 0.0)
                for r in negatives
                if r.abstained is not None
            ),
            "fabrication_rate": _safe_mean(
                (1.0 if r.fabricated else 0.0)
                for r in negatives
                if r.fabricated is not None
            ),
            "faithfulness_rate": _safe_mean(
                (1.0 if r.faithful else 0.0)
                for r in positives
                if r.faithful is not None
            ),
            # Routing (Phase 3)
            "routing_accuracy": _safe_mean(
                (1.0 if r.routing_correct else 0.0)
                for r in rs
                if r.routing_correct is not None
            ),
            # Cost / latency
            "avg_latency": _safe_mean(r.latency_seconds for r in rs),
        }

    def by_task_type(self) -> dict:
        out: dict[str, dict] = {}
        types = sorted({r.case.task_type for r in self.results})
        for t in types:
            subset = [r for r in self.results if r.case.task_type == t]
            out[t] = {
                "n": len(subset),
                "retrieval_recall_docs": _safe_mean(
                    r.retrieval_recall_docs for r in subset
                ),
                "answer_recall": _safe_mean(r.answer_recall for r in subset),
                "citation_correctness": _safe_mean(
                    r.citation_correctness for r in subset
                ),
            }
        return out

    def to_dict(self) -> dict:
        return {
            "prompt_version": self.prompt_version,
            "aggregate": self.aggregate(),
            "by_task_type": self.by_task_type(),
            "cases": [r.to_dict() for r in self.results],
        }

    def summary(self) -> str:
        agg = self.aggregate()

        def fmt(v):
            return "—" if v is None else f"{v}"

        lines = [
            f"RAG quality eval — {agg['n']} cases "
            f"({agg['n_positive']} positivos, {agg['n_negative']} negativos) "
            f"[prompts {agg['prompt_version']}]",
            "  Recall:",
            f"    retrieval_recall (docs)   : {fmt(agg['retrieval_recall_docs'])}",
            f"    retrieval_recall (pages)  : {fmt(agg['retrieval_recall_pages'])}",
            f"    answer_recall             : {fmt(agg['answer_recall'])}",
            "  Provenance:",
            f"    cited_any                 : {fmt(agg['cited_any'])}",
            f"    citation_correctness      : {fmt(agg['citation_correctness'])}",
            f"    expected_evidence_cited   : {fmt(agg['expected_evidence_cited'])}",
            "  Abstención / fidelidad:",
            f"    abstention_rate (neg)     : {fmt(agg['abstention_rate'])}",
            f"    fabrication_rate (neg)    : {fmt(agg['fabrication_rate'])}",
            f"    faithfulness_rate (pos)   : {fmt(agg['faithfulness_rate'])}",
            "  Routing:",
            f"    routing_accuracy          : {fmt(agg['routing_accuracy'])}",
            f"  avg latency (s)             : {fmt(agg['avg_latency'])}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generation step (mirrors the chat layer's prompt composition)
# ---------------------------------------------------------------------------

_ANSWER_SYSTEM_PROMPT = (
    "Eres Ecofilia, un asistente experto en ESG, cambio climático y biodiversidad. "
    "Respondé la pregunta del usuario usando EXCLUSIVAMENTE la información de los "
    "fragmentos de contexto provistos. Sé preciso y conciso. "
    "Si el dato pedido no está en los fragmentos, declaralo explícitamente en lugar "
    "de inventarlo."
)

_NO_CONTEXT_NOTE = (
    "No se recuperó ningún fragmento de contexto para esta consulta. "
    "Si no podés responder con evidencia documental, declaralo explícitamente."
)


def _generate_answer(
    result: RetrievalResult, question: str, *, model: str | None = None
) -> tuple[str, dict]:
    """Generate an answer mirroring production prompt composition."""
    from apps.document.utils.client_openia import generate_chat_completion

    query_type = (
        getattr(result.analysis, "query_type", None) if result.analysis else None
    )
    system_text = _ANSWER_SYSTEM_PROMPT + "\n\n" + build_citation_prompt(query_type)
    messages = [{"role": "system", "content": system_text}]
    if result.context_block:
        messages.append(
            {
                "role": "system",
                "content": "Contexto documental:\n\n" + result.context_block,
            }
        )
    else:
        messages.append({"role": "system", "content": _NO_CONTEXT_NOTE})
    messages.append({"role": "user", "content": question})

    text, usage = generate_chat_completion(
        messages,
        model=model or _ANSWER_MODEL,
        temperature=0.1,
        max_tokens=700,
        timeout=60,
    )
    return (text or "").strip(), (usage or {})


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------


def _run_judge(system: str, user: str, *, model: str | None = None) -> Optional[dict]:
    """Call the judge model and parse a JSON object. None on any failure."""
    try:
        from apps.document.utils.client_openia import generate_chat_completion

        body, _usage = generate_chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model or _JUDGE_MODEL,
            temperature=0.0,
            max_tokens=400,
            timeout=30,
        )
        body = (body or "").strip()
        match = re.search(r"\{[\s\S]*\}", body)
        if match:
            body = match.group(0)
        return json.loads(body)
    except Exception as exc:  # pragma: no cover - judge is best-effort
        logger.warning("LLM judge failed: %s", exc)
        return None


_JUDGE_RECALL_SYSTEM = (
    "Sos un evaluador estricto de respuestas. Te doy una RESPUESTA y una lista "
    "numerada de HECHOS ESPERADOS. Para cada hecho, decidí si la respuesta lo "
    "afirma EXPLÍCITAMENTE (true) o no (false). No infieras; exigí que el dato "
    "esté presente. Devolvé SOLO un JSON con la forma "
    '{"present": [true, false, ...]} en el mismo orden de los hechos.'
)


def _judge_answer_recall(answer: str, facts: List[str]) -> Optional[float]:
    if not facts:
        return None
    numbered = "\n".join(f"{i+1}. {f}" for i, f in enumerate(facts))
    data = _run_judge(
        _JUDGE_RECALL_SYSTEM,
        f"RESPUESTA:\n{answer}\n\nHECHOS ESPERADOS:\n{numbered}",
    )
    if not data:
        return None
    present = data.get("present")
    if not isinstance(present, list) or not present:
        return None
    hits = sum(1 for p in present if bool(p))
    return round(hits / len(facts), 3)


_JUDGE_ABSTENTION_SYSTEM = (
    "Te doy una PREGUNTA y una RESPUESTA. Contexto: la información pedida NO "
    "está en los documentos disponibles. Evaluá la respuesta: "
    "'abstained' = true si declara honestamente que no encontró evidencia / que "
    "el dato no está en los documentos. 'fabricated' = true si inventa un dato "
    "concreto como si fuera documental. Devolvé SOLO un JSON "
    '{"abstained": bool, "fabricated": bool}.'
)


def _judge_abstention(question: str, answer: str) -> Optional[dict]:
    data = _run_judge(
        _JUDGE_ABSTENTION_SYSTEM,
        f"PREGUNTA:\n{question}\n\nRESPUESTA:\n{answer}",
    )
    if not data:
        return None
    return {
        "abstained": bool(data.get("abstained", False)),
        "fabricated": bool(data.get("fabricated", False)),
    }


_JUDGE_FAITHFULNESS_SYSTEM = (
    "Te doy un CONTEXTO (fragmentos documentales) y una RESPUESTA. Decidí si "
    "TODA afirmación factual de la respuesta está respaldada por el contexto. "
    "'faithful' = true si todo está respaldado. Listá en 'unsupported' las "
    "afirmaciones no respaldadas (vacío si todo respaldado). Devolvé SOLO un "
    'JSON {"faithful": bool, "unsupported": ["..."]}.'
)


def _judge_faithfulness(context_block: str, answer: str) -> Optional[dict]:
    if not context_block:
        return None
    data = _run_judge(
        _JUDGE_FAITHFULNESS_SYSTEM,
        f"CONTEXTO:\n{context_block[:8000]}\n\nRESPUESTA:\n{answer}",
    )
    if not data:
        return None
    unsupported = data.get("unsupported")
    return {
        "faithful": bool(data.get("faithful", False)),
        "unsupported": [str(x) for x in unsupported]
        if isinstance(unsupported, list)
        else [],
    }


# ---------------------------------------------------------------------------
# Provenance scoring (deterministic)
# ---------------------------------------------------------------------------


def _page_matches(chunk_page, expected_page, tol: int = 1) -> bool:
    if chunk_page is None or expected_page is None:
        return False
    try:
        return abs(int(chunk_page) - int(expected_page)) <= tol
    except (TypeError, ValueError):
        return False


def _retrieval_recall_pages(
    chunks, expected_evidence: List[dict]
) -> Optional[float]:
    """Fraction of expected (doc, page) evidence locations present in chunks."""
    targets = [e for e in expected_evidence if e.get("page") is not None]
    if not targets:
        return None
    hits = 0
    for ev in targets:
        slug = ev.get("document_slug")
        page = ev.get("page")
        for c in chunks:
            doc = getattr(c, "document", None)
            if doc and getattr(doc, "slug", "") == slug and _page_matches(
                getattr(c, "page_number", None), page
            ):
                hits += 1
                break
    return round(hits / len(targets), 3)


def _score_citations(
    answer: str, chunks, case: QualityCase
) -> tuple[bool, Optional[float], Optional[bool]]:
    """Map [#N] citations to chunks and check they point at expected sources.

    Returns (cited_any, citation_correctness, expected_evidence_cited).
    citation_correctness is None when the answer cites nothing.
    """
    indices = [int(m) for m in _CITATION_RE.findall(answer or "")]
    cited_any = bool(indices)
    expected_slugs = {s for s in case.expected_document_slugs if s}

    if not indices or not expected_slugs:
        return cited_any, (None if not indices else None), None

    correct = 0
    cited_expected = False
    valid_citations = 0
    for n in indices:
        if n < 1 or n > len(chunks):
            continue
        valid_citations += 1
        chunk = chunks[n - 1]
        doc = getattr(chunk, "document", None)
        slug = getattr(doc, "slug", "") if doc else ""
        if slug in expected_slugs:
            correct += 1
            # Was the *specific* expected page cited (when we have page GT)?
            for ev in case.expected_evidence:
                if ev.get("document_slug") == slug and _page_matches(
                    getattr(chunk, "page_number", None), ev.get("page")
                ):
                    cited_expected = True
    citation_correctness = (
        round(correct / valid_citations, 3) if valid_citations else None
    )
    expected_evidence_cited = (
        cited_expected if case.expected_evidence else (correct > 0)
    )
    return cited_any, citation_correctness, expected_evidence_cited


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_quality_eval(
    cases: Iterable[QualityCase],
    *,
    user,
    allowed_documents: QuerySet[Document],
    top_n: int = 12,
    skip_generation: bool = False,
    skip_judge: bool = False,
) -> QualityReport:
    """Run retrieval + generation + judging for each case.

    ``skip_generation`` runs only the retrieval layer (fully offline, no LLM).
    ``skip_judge`` runs generation but skips the LLM-judge semantic metrics.
    """
    report = QualityReport()
    for case in cases:
        started = time.perf_counter()
        # Phase 5: drive the harness through the unified engine. ``skip_generation``
        # keeps a retrieval-only path (no LLM); otherwise the engine handles
        # retrieve → (fan-out | generate) → cited answer in one call.
        try:
            if skip_generation:
                retrieval = retrieve_for_chat(
                    user=user,
                    query_text=case.question,
                    allowed_documents=allowed_documents,
                    top_n=top_n,
                    total_limit=top_n,
                )
                chunks = list(retrieval.chunks)
                analysis = retrieval.analysis
                diagnostics = retrieval.diagnostics or {}
                context_block = retrieval.context_block
                answer, usage = "", {}
            else:
                eng = run_engine(
                    EngineRequest(
                        user=user,
                        query=case.question,
                        documents=allowed_documents,
                        top_n=top_n,
                        total_limit=top_n,
                    )
                )
                chunks = list(eng.chunks)
                analysis = eng.analysis
                diagnostics = eng.diagnostics or {}
                context_block = eng.context_block
                answer, usage = eng.answer, (eng.usage or {})
        except Exception as exc:  # pragma: no cover - eval is permissive
            logger.warning("Engine/retrieval failed for %r: %s", case.question, exc)
            report.results.append(
                _empty_result(case, latency=time.perf_counter() - started, error=str(exc))
            )
            continue

        slugs = [
            getattr(getattr(c, "document", None), "slug", "") or "" for c in chunks
        ]
        full_text = "\n".join((c.content or "") for c in chunks)

        routing_predicted = getattr(analysis, "query_type", "") if analysis else ""
        routing_correct = (
            routing_predicted == case.task_type
            if case.task_type in VALID_TASK_TYPES
            else None
        )

        retrieval_recall_docs = _coverage(slugs, case.expected_document_slugs)
        retrieval_recall_pages = _retrieval_recall_pages(chunks, case.expected_evidence)
        keyword_recall = _keyword_recall(full_text, case.expected_keywords)

        answer_recall = None
        cited_any = False
        citation_correctness = None
        expected_evidence_cited = None
        abstained = fabricated = faithful = None
        unsupported: List[str] = []

        if not skip_generation:
            cited_any, citation_correctness, expected_evidence_cited = _score_citations(
                answer, chunks, case
            )
            if answer and not skip_judge:
                if case.answer_exists:
                    answer_recall = _judge_answer_recall(answer, case.expected_facts)
                    faith = _judge_faithfulness(context_block, answer)
                    if faith is not None:
                        faithful = faith["faithful"]
                        unsupported = faith["unsupported"]
                else:
                    abst = _judge_abstention(case.question, answer)
                    if abst is not None:
                        abstained = abst["abstained"]
                        fabricated = abst["fabricated"]

        report.results.append(
            QualityCaseResult(
                case=case,
                retrieval_recall_docs=retrieval_recall_docs,
                retrieval_recall_pages=retrieval_recall_pages,
                keyword_recall=keyword_recall,
                num_chunks=len(chunks),
                unique_sources=len({s for s in slugs if s}),
                answer=answer,
                answer_recall=answer_recall,
                cited_any=cited_any,
                citation_correctness=citation_correctness,
                expected_evidence_cited=expected_evidence_cited,
                abstained=abstained,
                fabricated=fabricated,
                faithful=faithful,
                unsupported_claims=unsupported,
                latency_seconds=time.perf_counter() - started,
                usage=usage,
                retrieved_slugs=slugs,
                diagnostics=diagnostics,
                routing_predicted=routing_predicted,
                routing_correct=routing_correct,
            )
        )
    return report


def _empty_result(case: QualityCase, *, latency: float, error: str) -> QualityCaseResult:
    return QualityCaseResult(
        case=case,
        retrieval_recall_docs=0.0,
        retrieval_recall_pages=None,
        keyword_recall=0.0,
        num_chunks=0,
        unique_sources=0,
        answer="",
        answer_recall=None,
        cited_any=False,
        citation_correctness=None,
        expected_evidence_cited=None,
        abstained=None,
        fabricated=None,
        faithful=None,
        latency_seconds=latency,
        error=error,
    )


# ---------------------------------------------------------------------------
# Baseline diff
# ---------------------------------------------------------------------------


def diff_against_baseline(current: dict, baseline: dict) -> List[str]:
    """Human-readable deltas between two aggregate dicts (current vs baseline)."""
    cur = current.get("aggregate", current)
    base = baseline.get("aggregate", baseline)
    keys = [
        "retrieval_recall_docs",
        "retrieval_recall_pages",
        "answer_recall",
        "cited_any",
        "citation_correctness",
        "expected_evidence_cited",
        "abstention_rate",
        "fabrication_rate",
        "faithfulness_rate",
        "avg_latency",
    ]
    lines = ["Δ vs baseline:"]
    for k in keys:
        c = cur.get(k)
        b = base.get(k)
        if c is None and b is None:
            continue
        if c is None or b is None:
            lines.append(f"  {k:26s}: {b} -> {c}")
            continue
        delta = round(c - b, 3)
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
        lines.append(f"  {k:26s}: {b} -> {c}  ({arrow}{abs(delta)})")
    return lines
