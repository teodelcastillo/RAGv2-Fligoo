from __future__ import annotations

import logging
import os
import re
from typing import List
from django.utils import timezone

from apps.chat.services.rag import build_context_block, fetch_relevant_chunks
from apps.document.models import Document
from apps.document.utils.client_openia import generate_chat_completion
from apps.evaluation.models import (
    EvaluationRun,
    EvaluationRunStatus,
    MetricEvaluationResult,
    MetricResponseType,
    PillarEvaluationResult,
)

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_CHUNKS = int(
    os.environ.get("EVALUATION_CONTEXT_CHUNKS", os.environ.get("CHAT_CONTEXT_CHUNKS", "4"))
)


class EvaluationRunner:
    """
    Ejecuta una evaluación pillar → métricas utilizando RAG + LLM.
    """

    def __init__(self, *, chunks_per_metric: int | None = None):
        self.chunks_per_metric = chunks_per_metric or DEFAULT_CONTEXT_CHUNKS

    def run(self, run_id: int) -> EvaluationRun:
        run = (
            EvaluationRun.objects.select_related("evaluation", "owner", "project")
            .prefetch_related("evaluation__pillars__metrics")
            .get(pk=run_id)
        )
        if run.status not in (EvaluationRunStatus.PENDING, EvaluationRunStatus.FAILED):
            return run

        documents_qs = self._documents_for_run(run)
        if not documents_qs.exists():
            message = "La ejecución no tiene documentos asociados."
            logger.error("Run %s aborted: %s", run.id, message)
            run.status = EvaluationRunStatus.FAILED
            run.error_message = message
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])
            return run

        logger.info("Starting evaluation run %s with %s documents.", run.id, documents_qs.count())
        run.status = EvaluationRunStatus.RUNNING
        run.error_message = ""
        run.started_at = timezone.now()
        run.pillar_results.all().delete()
        run.save(update_fields=["status", "error_message", "started_at"])

        try:
            self._process_pillars(run, documents_qs)
        except Exception as exc:  # pragma: no cover - defensive, tested via mocks
            logger.exception("Evaluation run %s failed", run.id)
            run.status = EvaluationRunStatus.FAILED
            run.error_message = str(exc)
        else:
            run.status = EvaluationRunStatus.COMPLETED
        finally:
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])

        return run

    def _process_pillars(self, run: EvaluationRun, documents_qs):
        evaluation = run.evaluation
        for pillar in evaluation.pillars.all():
            pillar_result = PillarEvaluationResult.objects.create(
                run=run,
                pillar=pillar,
                position=pillar.position,
                summary="",
            )
            pillar_chunk_ids: List[int] = []
            pillar_sources: List[dict] = []
            for metric in pillar.metrics.all():
                metric_result = self._evaluate_metric(
                    run=run,
                    pillar=pillar,
                    metric=metric,
                    documents_qs=documents_qs,
                )
                metric_result.pillar_result = pillar_result
                metric_result.position = metric.position
                metric_result.save()
                pillar_chunk_ids.extend(metric_result.chunk_ids or [])
                pillar_sources.extend(metric_result.sources or [])

            pillar_result.summary = pillar.context_instructions or f"Resultados del pilar {pillar.title}."
            pillar_result.chunk_ids = pillar_chunk_ids
            pillar_result.sources = pillar_sources
            pillar_result.save(update_fields=["summary", "chunk_ids", "sources"])

    def _evaluate_metric(self, *, run, pillar, metric, documents_qs):
        query_text = self._build_query_text(pillar, metric, run)
        chunks = fetch_relevant_chunks(
            user=run.owner,
            query_text=query_text,
            allowed_documents=documents_qs,
            top_n=self.chunks_per_metric,
        )
        context_block = build_context_block(chunks)
        prompt = self._build_prompt(run, pillar, metric, context_block)
        messages = [
            {"role": "system", "content": run.evaluation.system_prompt},
            {"role": "user", "content": prompt},
        ]
        response_text, usage = generate_chat_completion(
            messages,
            model=run.model,
            temperature=run.temperature,
        )
        response_value = None
        if metric.response_type == MetricResponseType.QUANTITATIVE:
            response_value = self._extract_numeric_value(
                response_text, metric.scale_min, metric.scale_max
            )

        chunk_ids = [chunk.id for chunk in chunks]
        sources = [
            {
                "chunk_id": chunk.id,
                "document_slug": chunk.document.slug,
                "document_name": chunk.document.name,
                "chunk_index": chunk.chunk_index,
                "distance": getattr(chunk, "distance", None),
            }
            for chunk in chunks
        ]

        metric_result = MetricEvaluationResult(
            metric=metric,
            response_type=metric.response_type,
            response_text=response_text,
            response_value=response_value,
            chunk_ids=chunk_ids,
            sources=sources,
            metadata={"usage": usage},
        )
        return metric_result

    def _documents_for_run(self, run: EvaluationRun):
        snapshot = run.document_snapshot or []
        doc_ids = [entry.get("id") for entry in snapshot if entry.get("id")]
        return Document.objects.filter(id__in=doc_ids)

    def _build_query_text(self, pillar, metric, run):
        parts = [
            metric.instructions or "",
            metric.criteria or "",
            pillar.context_instructions or "",
            run.instructions_override or "",
        ]
        return "\n".join(part for part in parts if part).strip()

    def _build_prompt(self, run, pillar, metric, context_block: str) -> str:
        language = run.language or "es"
        lines = [
            f"Evaluación: {run.evaluation.title}",
            f"Pilar: {pillar.title}",
        ]
        if pillar.context_instructions:
            lines.append(f"Contexto del pilar:\n{pillar.context_instructions}")
        lines.append(f"Instrucciones del KPI:\n{metric.instructions}")
        if metric.criteria:
            lines.append(f"Criterios adicionales:\n{metric.criteria}")
        if metric.response_type == MetricResponseType.QUANTITATIVE:
            scale = f"El resultado debe ser numérico"
            if metric.scale_min is not None and metric.scale_max is not None:
                scale += f" entre {metric.scale_min} y {metric.scale_max}"
            scale += "."
            if metric.expected_units:
                scale += f" Unidades esperadas: {metric.expected_units}."
            lines.append(scale)
        else:
            lines.append("Entrega un análisis cualitativo/descriptivo.")

        if run.instructions_override:
            lines.append(f"Instrucciones adicionales del usuario:\n{run.instructions_override}")

        if context_block:
            lines.append("Contexto documental:\n" + context_block)
        else:
            lines.append("No se encontraron fragmentos relevantes; indica claramente si falta contexto.")

        lines.append(f"Responde en idioma: {language}. Referencia siempre las fuentes proporcionadas.")
        return "\n\n".join(lines)

    def _extract_numeric_value(self, text: str, scale_min, scale_max):
        if not text:
            return None
        matches = re.findall(r"-?\d+(?:[.,]\d+)?", text)
        for match in matches:
            value = float(match.replace(",", "."))
            if scale_min is not None and value < scale_min:
                continue
            if scale_max is not None and value > scale_max:
                continue
            return value
        return None


def execute_evaluation_run(run: EvaluationRun) -> EvaluationRun:
    runner = EvaluationRunner()
    return runner.run(run.id)
