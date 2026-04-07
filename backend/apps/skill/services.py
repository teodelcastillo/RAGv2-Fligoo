from __future__ import annotations

import logging
import os
from typing import List

from django.db.models import QuerySet
from django.utils import timezone

from apps.chat.services.rag import build_context_block, fetch_relevant_chunks
from apps.document.models import Document
from apps.document.utils.client_openia import generate_chat_completion
from apps.skill.models import (
    ExecutionStatus,
    RetrievalStrategy,
    Skill,
    SkillExecution,
    SkillStep,
    SkillType,
)

logger = logging.getLogger(__name__)

DEFAULT_CHUNKS = int(os.environ.get("SKILL_CONTEXT_CHUNKS", "6"))


# ---------------------------------------------------------------------------
# Document resolver
# ---------------------------------------------------------------------------

def resolve_documents(execution: SkillExecution) -> QuerySet[Document]:
    """
    Returns the queryset of documents available for this execution context.
    - Repository: only is_active=True documents
    - Project: all linked documents
    - Document: the single document
    """
    if execution.repository_id:
        from apps.repository.models import RepositoryDocument
        doc_ids = (
            RepositoryDocument.objects
            .filter(repository_id=execution.repository_id, is_active=True)
            .values_list("document_id", flat=True)
        )
        return Document.objects.filter(id__in=doc_ids)

    if execution.project_id:
        from apps.project.models import ProjectDocument
        doc_ids = (
            ProjectDocument.objects
            .filter(project_id=execution.project_id)
            .values_list("document_id", flat=True)
        )
        return Document.objects.filter(id__in=doc_ids)

    if execution.document_id:
        return Document.objects.filter(id=execution.document_id)

    return Document.objects.none()


def build_document_snapshot(documents: QuerySet[Document]) -> list:
    return [
        {"id": d.id, "slug": d.slug, "name": d.name}
        for d in documents.only("id", "slug", "name")
    ]


# ---------------------------------------------------------------------------
# Quick skill runner
# ---------------------------------------------------------------------------

def _render_quick_prompt(template: str, context_block: str, extra_instructions: str) -> str:
    prompt = template.replace("{{context}}", context_block or "(No document content found)")
    prompt = prompt.replace("{{extra_instructions}}", extra_instructions or "")
    return prompt.strip()


def _comparative_instruction_block(strict_missing_evidence: bool) -> str:
    lines = [
        "Comparative output requirements:",
        "1) Present findings by document first for each criterion.",
        "2) For every criterion, include every active document even if there is no direct evidence.",
    ]
    if strict_missing_evidence:
        lines.append(
            "3) If a document does not contain evidence for a criterion, explicitly write: "
            "'Sin evidencia en fuentes provistas'."
        )
    else:
        lines.append(
            "3) If evidence is missing, state that limitation clearly and avoid unsupported inference."
        )
    return "\n".join(lines).strip()


def _collect_source_stats(chunks, total_docs: int) -> dict:
    docs_covered = set()
    chunks_per_document = {}
    for c in chunks:
        docs_covered.add(c.document.slug)
        chunks_per_document[c.document.slug] = chunks_per_document.get(c.document.slug, 0) + 1
    return {
        "docs_total": total_docs,
        "docs_covered": len(docs_covered),
        "doc_coverage_ratio": round((len(docs_covered) / total_docs), 4) if total_docs else 0,
        "chunks_per_document": chunks_per_document,
    }


def _run_quick(execution: SkillExecution, documents: QuerySet[Document]) -> None:
    skill = execution.skill
    query_text = f"{skill.name}. {skill.description}. {execution.extra_instructions}".strip()
    effective_retrieval_strategy = (
        RetrievalStrategy.HYBRID_PER_DOCUMENT
        if skill.comparative_mode_enabled
        else skill.retrieval_strategy
    )

    chunks = fetch_relevant_chunks(
        user=execution.owner,
        query_text=query_text,
        allowed_documents=documents,
        top_n=DEFAULT_CHUNKS,
        retrieval_strategy=effective_retrieval_strategy,
        k_per_doc=skill.k_per_doc,
        total_limit=skill.total_limit,
        max_chunks_per_doc=skill.max_per_doc_after_rerank,
    )
    context_block = build_context_block(chunks)

    prompt = _render_quick_prompt(
        skill.prompt_template, context_block, execution.extra_instructions
    )
    if skill.comparative_mode_enabled:
        prompt = (
            f"{prompt}\n\n{_comparative_instruction_block(skill.strict_missing_evidence)}"
        ).strip()
    messages = [
        {"role": "system", "content": skill.system_prompt},
        {"role": "user", "content": prompt},
    ]
    output_text, usage = generate_chat_completion(
        messages, model=skill.model, temperature=skill.temperature
    )

    execution.output = output_text
    source_stats = _collect_source_stats(chunks, total_docs=documents.count())
    execution.metadata = {
        "usage": usage,
        "chunks_used": len(chunks),
        "comparative_mode_enabled": skill.comparative_mode_enabled,
        "strict_missing_evidence": skill.strict_missing_evidence,
        "retrieval_strategy_used": effective_retrieval_strategy,
        **source_stats,
        "sources": [
            {
                "document_slug": c.document.slug,
                "document_name": c.document.name,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ],
    }


# ---------------------------------------------------------------------------
# Copilot skill runner
# ---------------------------------------------------------------------------

def _run_copilot(execution: SkillExecution, documents: QuerySet[Document]) -> None:
    skill = execution.skill
    steps: List[SkillStep] = list(skill.steps.all())
    if not steps:
        raise ValueError("This Copilot skill has no steps defined.")

    step_results = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # Build a running summary of previous steps to feed as context
    previous_outputs: List[str] = []
    all_step_chunks = []
    effective_retrieval_strategy = (
        RetrievalStrategy.HYBRID_PER_DOCUMENT
        if skill.comparative_mode_enabled
        else skill.retrieval_strategy
    )

    for step in steps:
        query_text = f"{step.title}. {step.instructions}".strip()

        chunks = fetch_relevant_chunks(
            user=execution.owner,
            query_text=query_text,
            allowed_documents=documents,
            top_n=DEFAULT_CHUNKS,
            retrieval_strategy=effective_retrieval_strategy,
            k_per_doc=skill.k_per_doc,
            total_limit=skill.total_limit,
            max_chunks_per_doc=skill.max_per_doc_after_rerank,
        )
        all_step_chunks.extend(chunks)
        context_block = build_context_block(chunks)

        # Compose the full prompt for this step
        lines = [
            f"## Task: {step.title}",
            "",
            f"Instructions: {step.instructions}",
        ]
        if execution.extra_instructions:
            lines.append(f"\nAdditional instructions from user: {execution.extra_instructions}")
        if previous_outputs:
            lines.append("\n## Previous sections already written:")
            for prev in previous_outputs:
                lines.append(prev)
        if context_block:
            lines.append(f"\n## Document context:\n{context_block}")
        else:
            lines.append("\n(No document content found for this section — note this in your output.)")
        if skill.comparative_mode_enabled:
            lines.append(f"\n## Comparative constraints:\n{_comparative_instruction_block(skill.strict_missing_evidence)}")

        prompt = "\n".join(lines)
        messages = [
            {"role": "system", "content": skill.system_prompt},
            {"role": "user", "content": prompt},
        ]
        content, usage = generate_chat_completion(
            messages, model=skill.model, temperature=skill.temperature
        )

        step_results.append({"step_id": step.id, "title": step.title, "content": content})
        previous_outputs.append(f"### {step.title}\n{content}")

        for key in total_usage:
            total_usage[key] += usage.get(key, 0)

    execution.output_structured = {"steps": step_results}
    source_stats = _collect_source_stats(all_step_chunks, total_docs=documents.count())
    execution.metadata = {
        "usage": total_usage,
        "comparative_mode_enabled": skill.comparative_mode_enabled,
        "strict_missing_evidence": skill.strict_missing_evidence,
        "retrieval_strategy_used": effective_retrieval_strategy,
        **source_stats,
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

class SkillRunner:
    def run(self, execution_id: int) -> SkillExecution:
        execution = (
            SkillExecution.objects
            .select_related("skill", "owner", "repository", "project", "document")
            .prefetch_related("skill__steps")
            .get(pk=execution_id)
        )

        if execution.status not in (ExecutionStatus.PENDING, ExecutionStatus.FAILED):
            return execution

        documents = resolve_documents(execution)
        if not documents.exists():
            execution.status = ExecutionStatus.FAILED
            execution.error_message = (
                "No documents found for this context. "
                "Make sure the repository/project has active sources."
            )
            execution.finished_at = timezone.now()
            execution.save(update_fields=["status", "error_message", "finished_at"])
            return execution

        execution.status = ExecutionStatus.RUNNING
        execution.started_at = timezone.now()
        execution.document_snapshot = build_document_snapshot(documents)
        execution.error_message = ""
        execution.save(update_fields=["status", "started_at", "document_snapshot", "error_message"])

        try:
            if execution.skill.skill_type == SkillType.QUICK:
                _run_quick(execution, documents)
            else:
                _run_copilot(execution, documents)
            execution.status = ExecutionStatus.COMPLETED
        except Exception as exc:
            logger.exception("SkillExecution %s failed", execution.id)
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(exc)
        finally:
            execution.finished_at = timezone.now()
            execution.save(update_fields=[
                "status", "output", "output_structured", "metadata",
                "error_message", "finished_at",
            ])

        return execution


def execute_skill(execution: SkillExecution) -> SkillExecution:
    return SkillRunner().run(execution.id)
