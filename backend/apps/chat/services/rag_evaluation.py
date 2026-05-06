"""
Lightweight evaluation harness for the RAG pipeline.

This module provides primitives to run offline evals against a small dataset
of (question, expected_document_slugs, expected_keywords) triples and produce
metrics suitable for tracking progress over time.

The harness is intentionally dependency-free (no pytest, no pandas) so it can
be invoked from a Django shell, a management command, or a future CI job.

Typical usage:

    from apps.chat.services.rag_evaluation import RagEvalCase, run_eval
    cases = [
        RagEvalCase(
            question="¿Qué dice el reporte 2024 sobre emisiones?",
            expected_document_slugs=["reporte-2024"],
            expected_keywords=["emisiones", "alcance"],
        ),
    ]
    report = run_eval(cases, user=user, allowed_documents=docs_qs)
    print(report.summary())

Metrics computed per case:
- coverage@k: fraction of expected_documents present in retrieved chunks.
- keyword_recall@k: fraction of expected_keywords present in concatenated text.
- unique_sources: number of distinct documents in the final context.
- num_chunks, latency_seconds.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, List

from django.db.models import QuerySet

from apps.chat.services.rag import retrieve_for_chat
from apps.document.models import Document

logger = logging.getLogger(__name__)


@dataclass
class RagEvalCase:
    question: str
    expected_document_slugs: List[str] = field(default_factory=list)
    expected_keywords: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class RagEvalCaseResult:
    case: RagEvalCase
    coverage: float
    keyword_recall: float
    unique_sources: int
    num_chunks: int
    latency_seconds: float
    diagnostics: dict


@dataclass
class RagEvalReport:
    results: List[RagEvalCaseResult] = field(default_factory=list)

    def aggregate(self) -> dict:
        if not self.results:
            return {
                "n": 0,
                "avg_coverage": 0.0,
                "avg_keyword_recall": 0.0,
                "avg_unique_sources": 0.0,
                "avg_chunks": 0.0,
                "avg_latency": 0.0,
            }
        return {
            "n": len(self.results),
            "avg_coverage": round(mean(r.coverage for r in self.results), 3),
            "avg_keyword_recall": round(
                mean(r.keyword_recall for r in self.results), 3
            ),
            "avg_unique_sources": round(
                mean(r.unique_sources for r in self.results), 2
            ),
            "avg_chunks": round(mean(r.num_chunks for r in self.results), 2),
            "avg_latency": round(mean(r.latency_seconds for r in self.results), 3),
        }

    def summary(self) -> str:
        agg = self.aggregate()
        lines = [
            f"RAG eval — {agg['n']} cases",
            f"  coverage@k        : {agg['avg_coverage']}",
            f"  keyword_recall@k  : {agg['avg_keyword_recall']}",
            f"  avg unique sources: {agg['avg_unique_sources']}",
            f"  avg chunks        : {agg['avg_chunks']}",
            f"  avg latency (s)   : {agg['avg_latency']}",
        ]
        return "\n".join(lines)


def _coverage(retrieved_slugs: Iterable[str], expected: Iterable[str]) -> float:
    expected_set = {s for s in expected if s}
    if not expected_set:
        return 1.0
    retrieved_set = {s for s in retrieved_slugs if s}
    return len(expected_set & retrieved_set) / len(expected_set)


def _keyword_recall(text: str, keywords: Iterable[str]) -> float:
    keys = [k.lower() for k in keywords if k]
    if not keys:
        return 1.0
    blob = (text or "").lower()
    hits = sum(1 for k in keys if k in blob)
    return hits / len(keys)


def run_eval(
    cases: Iterable[RagEvalCase],
    *,
    user,
    allowed_documents: QuerySet[Document],
    top_n: int = 12,
) -> RagEvalReport:
    """Execute the pipeline for each case and return a structured report."""
    report = RagEvalReport()
    for case in cases:
        started = time.perf_counter()
        try:
            result = retrieve_for_chat(
                user=user,
                query_text=case.question,
                allowed_documents=allowed_documents,
                top_n=top_n,
                total_limit=top_n,
            )
        except Exception as exc:  # pragma: no cover - eval should be permissive
            logger.warning("Eval case failed: %s -> %s", case.question, exc)
            report.results.append(
                RagEvalCaseResult(
                    case=case,
                    coverage=0.0,
                    keyword_recall=0.0,
                    unique_sources=0,
                    num_chunks=0,
                    latency_seconds=time.perf_counter() - started,
                    diagnostics={"error": str(exc)},
                )
            )
            continue

        slugs = []
        full_text_parts = []
        for chunk in result.chunks:
            doc = getattr(chunk, "document", None)
            slug = getattr(doc, "slug", "") if doc else ""
            if slug:
                slugs.append(slug)
            full_text_parts.append(chunk.content or "")

        full_text = "\n".join(full_text_parts)
        coverage = _coverage(slugs, case.expected_document_slugs)
        kw_recall = _keyword_recall(full_text, case.expected_keywords)
        unique_sources = len(set(slugs))

        report.results.append(
            RagEvalCaseResult(
                case=case,
                coverage=coverage,
                keyword_recall=kw_recall,
                unique_sources=unique_sources,
                num_chunks=len(result.chunks),
                latency_seconds=time.perf_counter() - started,
                diagnostics=result.diagnostics or {},
            )
        )
    return report
