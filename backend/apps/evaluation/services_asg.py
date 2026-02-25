"""
ASG Allen Manza evaluation service.

Executes template-based evaluations on projects using RAG + OpenAI.
Produces structured KPI scores (0-10) with evidence for dashboard visualization.
"""
from __future__ import annotations

import json
import logging
import os
import re
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.chat.services.rag import build_context_block, fetch_relevant_chunks
from apps.document.models import Document
from apps.document.utils.client_openia import generate_chat_completion
from apps.evaluation.models_template import (
    EvaluationKPITemplate,
    EvaluationPillarTemplate,
    EvaluationTemplate,
    TemplateEvaluationRun,
    TemplateEvaluationRunScore,
    TemplateEvaluationRunStatus,
)
from apps.project.models import Project, ProjectDocument

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_CHUNKS = int(
    os.environ.get("EVALUATION_CONTEXT_CHUNKS", os.environ.get("CHAT_CONTEXT_CHUNKS", "4"))
)
DEFAULT_MODEL = os.environ.get("MODEL_COMPLETION", "gpt-4o-mini")


SYSTEM_PROMPT = """Eres un experto en evaluación ASG (Ambiental, Social y Gobernanza) para instituciones financieras.
Evalúa la información proporcionada según la metodología ASG Allen Manza.
Responde ÚNICAMENTE con un JSON válido en el formato:
{"score": <número 0-10>, "evidence": "<texto breve que justifica el puntaje>"}
El score debe ser un número entre 0 y 10.
Si no hay información suficiente, usa score bajo y explica en evidence."""


def run_asg_evaluation(
    *,
    project: Project,
    template: EvaluationTemplate,
    user,
    model: str | None = None,
) -> TemplateEvaluationRun:
    """
    Execute ASG evaluation on a project, persist scores and return the run.
    """
    run = TemplateEvaluationRun.objects.create(
        project=project,
        template=template,
        status=TemplateEvaluationRunStatus.RUNNING,
    )

    documents_qs = _documents_for_project(project)
    if not documents_qs.exists():
        run.status = TemplateEvaluationRunStatus.FAILED
        run.metadata = {"error": "El proyecto no tiene documentos con chunks procesados."}
        run.save()
        return run

    try:
        template = (
            EvaluationTemplate.objects.prefetch_related(
                "pillars__kpis",
            )
            .get(pk=template.pk)
        )
        for pillar in template.pillars.all():
            for kpi in pillar.kpis.all():
                score, evidence = _evaluate_kpi(
                    user=user,
                    kpi=kpi,
                    pillar=pillar,
                    documents_qs=documents_qs,
                    model=model or DEFAULT_MODEL,
                )
                TemplateEvaluationRunScore.objects.create(
                    run=run,
                    kpi=kpi,
                    score=score,
                    evidence=evidence,
                )
        run.status = TemplateEvaluationRunStatus.COMPLETED
    except Exception as exc:
        logger.exception("ASG evaluation run %s failed", run.id)
        run.status = TemplateEvaluationRunStatus.FAILED
        run.metadata = {"error": str(exc)}
    finally:
        run.save()

    return run


def _documents_for_project(project: Project):
    """Return documents linked to the project that have SmartChunks."""
    from apps.document.models import SmartChunk

    doc_ids = ProjectDocument.objects.filter(project=project).values_list("document_id", flat=True)
    # Only documents that have at least one chunk
    chunk_doc_ids = SmartChunk.objects.filter(document_id__in=doc_ids).values_list(
        "document_id", flat=True
    ).distinct()
    return Document.objects.filter(id__in=chunk_doc_ids)


def _evaluate_kpi(
    *,
    user,
    kpi: EvaluationKPITemplate,
    pillar: EvaluationPillarTemplate,
    documents_qs,
    model: str,
) -> tuple[Decimal, str]:
    """Evaluate a single KPI using RAG + LLM. Returns (score, evidence)."""
    query_text = f"{pillar.name} {kpi.name} {kpi.code}"
    chunks = fetch_relevant_chunks(
        user=user,
        query_text=query_text,
        allowed_documents=documents_qs,
        top_n=DEFAULT_CONTEXT_CHUNKS,
    )
    context_block = build_context_block(chunks)

    prompt = f"""Evaluar el siguiente KPI según la metodología ASG Allen Manza.
Pilar: {pillar.code} - {pillar.name}
KPI: {kpi.code} - {kpi.name}
Escala máxima del KPI: 0-{kpi.max_score} (normalizar a 0-10 en tu respuesta).

Contexto documental:
{context_block or "No se encontraron fragmentos relevantes."}

Responde ÚNICAMENTE con un JSON válido en el formato:
{{"score": <número 0-10>, "evidence": "<texto breve que justifica el puntaje>"}}"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    response_text, _ = generate_chat_completion(
        messages,
        model=model,
        temperature=0.1,
    )

    score, evidence = _parse_score_response(response_text)
    return score, evidence


def _parse_score_response(text: str) -> tuple[Decimal, str]:
    """Parse LLM response to extract score and evidence."""
    score = Decimal("0")
    evidence = ""

    # Try JSON parse first
    try:
        # Extract JSON block if wrapped in markdown
        json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            score = Decimal(str(data.get("score", 0)))
            evidence = str(data.get("evidence", ""))[:2000]
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: extract numeric score
    if score < 0 or score > 10:
        matches = re.findall(r"-?\d+(?:[.,]\d+)?", text)
        for match in matches:
            val = float(match.replace(",", "."))
            if 0 <= val <= 10:
                score = Decimal(str(val))
                break

    score = max(Decimal("0"), min(Decimal("10"), score))
    return score, evidence


def execute_asg_evaluation_sync(
    project_id: int,
    template_id: str,
    user,
) -> TemplateEvaluationRun:
    """Synchronous wrapper for running ASG evaluation."""
    project = Project.objects.get(pk=project_id)
    template = EvaluationTemplate.objects.get(pk=template_id)
    return run_asg_evaluation(project=project, template=template, user=user)
