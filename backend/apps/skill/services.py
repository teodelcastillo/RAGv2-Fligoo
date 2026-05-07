from __future__ import annotations

import json
import logging
import os
from typing import List

from django.db.models import QuerySet
from django.utils import timezone

from apps.chat.services.rag import build_context_block, fetch_relevant_chunks
from apps.document.models import Document
from apps.document.utils.client_openia import generate_chat_completion
from apps.skill.models import (
    ExecutionOutputMode,
    ExecutionStatus,
    RetrievalStrategy,
    SkillExecution,
    SkillStep,
    SkillType,
)
from apps.skill.table_schema import schema_has_columns

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
# Prompt helpers
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


# ---------------------------------------------------------------------------
# Table prompt + validation helpers (reused by Quick and Copilot steps)
# ---------------------------------------------------------------------------

def build_table_system_prompt(base_system_prompt: str, table_schema: dict) -> str:
    """
    Build the system prompt that forces the model to emit JSON matching the
    expected table schema, including per-column hints when provided.
    """
    columns = table_schema.get("columns") or []
    columns_json = json.dumps(columns, ensure_ascii=False)
    column_instructions = []
    for column in columns:
        prompt_hint = (column.get("prompt_hint") or "").strip()
        if not prompt_hint:
            continue
        column_instructions.append(
            f"- {column.get('key')} ({column.get('type')}): {prompt_hint}"
        )
    column_instructions_block = (
        "\n".join(column_instructions) or "- No extra per-column hints."
    )
    return (
        f"{base_system_prompt}\n\n"
        "Debes responder EXCLUSIVAMENTE en JSON válido (sin markdown, sin texto adicional) "
        "con este schema:\n"
        '{"type":"table","columns":[string],"rows":[object]}\n'
        "Usa EXACTAMENTE estas columnas y metadatos en este orden: "
        f"{columns_json}. "
        "Cada fila debe incluir todas las columnas con su tipo esperado."
        "\n\nInstrucciones por columna:\n"
        f"{column_instructions_block}"
    )


def coerce_table_output(*, output_text: str, table_schema: dict) -> dict:
    """
    Parse and normalize a model's tabular JSON response against the schema.

    Returns:
        {
            "type": "table",
            "columns": [str],          # ordered keys
            "column_schema": [dict],   # full column metadata
            "rows": [dict],            # normalized rows keyed by column key
        }
    """
    schema_columns = table_schema.get("columns") or []
    normalized_keys = [c.get("key") for c in schema_columns if c.get("key")]
    if not normalized_keys or not schema_columns:
        raise ValueError("Missing required columns for table output.")

    try:
        parsed = json.loads((output_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("Model returned invalid JSON for table output.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Table output must be a JSON object.")
    rows = parsed.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Table output must contain a 'rows' array.")

    type_map = {c["key"]: c.get("type", "text") for c in schema_columns}
    required_map = {c["key"]: bool(c.get("required", False)) for c in schema_columns}
    enum_map = {c["key"]: set(c.get("allowed_values") or []) for c in schema_columns}

    normalized_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized_row = {}
        for col in normalized_keys:
            value = row.get(col, None)
            value = normalize_table_cell_value(
                value=value,
                col_type=type_map.get(col, "text"),
                required=required_map.get(col, False),
                allowed_values=enum_map.get(col, set()),
            )
            normalized_row[col] = value
        normalized_rows.append(normalized_row)

    return {
        "type": "table",
        "columns": normalized_keys,
        "column_schema": schema_columns,
        "rows": normalized_rows,
    }


def normalize_table_cell_value(*, value, col_type: str, required: bool, allowed_values: set):
    """Best-effort normalization of a model-generated cell value to the column type."""
    if value in (None, ""):
        return ""
    if col_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "si", "sí"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        return ""
    if col_type == "number":
        try:
            number = float(value)
            if number.is_integer():
                return int(number)
            return number
        except (TypeError, ValueError):
            return ""
    if col_type == "enum":
        text = str(value).strip()
        if text in allowed_values:
            return text
        lowered = {str(v).lower(): v for v in allowed_values}
        mapped = lowered.get(text.lower())
        return mapped if mapped is not None else ""
    return str(value).strip()


def _table_summary_for_history(title: str, table: dict) -> str:
    """Compact representation of a tabular step output for follow-up steps."""
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    return f"### {title}\n[Tabla generada con {len(rows)} fila(s) y columnas: {', '.join(columns)}]"


# ---------------------------------------------------------------------------
# Quick skill runner
# ---------------------------------------------------------------------------

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

    is_table = execution.output_mode == ExecutionOutputMode.TABLE
    table_schema = execution.metadata.get("table_schema") or {}

    system_prompt = (
        build_table_system_prompt(skill.system_prompt, table_schema)
        if is_table
        else skill.system_prompt
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    output_text, usage = generate_chat_completion(
        messages, model=skill.model, temperature=skill.temperature
    )

    if is_table:
        parsed = coerce_table_output(output_text=output_text, table_schema=table_schema)
        execution.output = ""
        execution.output_structured = parsed
    else:
        execution.output = output_text
        execution.output_structured = {}

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
        "table_columns": execution.metadata.get("table_columns", []),
        "table_schema": execution.metadata.get("table_schema", {}),
    }


# ---------------------------------------------------------------------------
# Copilot skill runner
# ---------------------------------------------------------------------------

def _resolve_step_output_config(step: SkillStep) -> tuple[str, dict]:
    """
    Resolve the effective output mode and table schema for a single step.

    Steps default to TEXT. If the step is configured with TABLE but no
    table_schema, the step is downgraded to text instead of failing — this
    keeps the runner forgiving for legacy data while warnings are surfaced
    in metadata.
    """
    output_mode = step.output_mode or ExecutionOutputMode.TEXT
    table_schema = step.table_schema or {}
    if output_mode == ExecutionOutputMode.TABLE and not schema_has_columns(table_schema):
        return ExecutionOutputMode.TEXT, {}
    return output_mode, table_schema


def _run_copilot(execution: SkillExecution, documents: QuerySet[Document]) -> None:
    skill = execution.skill
    steps: List[SkillStep] = list(skill.steps.all())
    if not steps:
        raise ValueError("This Copilot skill has no steps defined.")

    step_results: list[dict] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    previous_outputs: List[str] = []
    all_step_chunks = []
    effective_retrieval_strategy = (
        RetrievalStrategy.HYBRID_PER_DOCUMENT
        if skill.comparative_mode_enabled
        else skill.retrieval_strategy
    )

    for step in steps:
        step_output_mode, step_table_schema = _resolve_step_output_config(step)
        is_table_step = step_output_mode == ExecutionOutputMode.TABLE

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

        # Compose the user prompt for this step
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
        if skill.comparative_mode_enabled and not is_table_step:
            lines.append(
                f"\n## Comparative constraints:\n{_comparative_instruction_block(skill.strict_missing_evidence)}"
            )

        prompt = "\n".join(lines)
        system_prompt = (
            build_table_system_prompt(skill.system_prompt, step_table_schema)
            if is_table_step
            else skill.system_prompt
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        content, usage = generate_chat_completion(
            messages, model=skill.model, temperature=skill.temperature
        )

        step_entry: dict = {
            "step_id": step.id,
            "title": step.title,
            "output_mode": step_output_mode,
        }
        if is_table_step:
            try:
                table = coerce_table_output(
                    output_text=content, table_schema=step_table_schema
                )
            except ValueError as exc:
                logger.warning(
                    "Step %s of execution %s produced invalid table JSON: %s",
                    step.id,
                    execution.id,
                    exc,
                )
                step_entry["output_mode"] = ExecutionOutputMode.TEXT
                step_entry["content"] = content
                step_entry["table_error"] = str(exc)
                previous_outputs.append(f"### {step.title}\n{content}")
            else:
                step_entry["table"] = table
                step_entry["content"] = ""
                previous_outputs.append(_table_summary_for_history(step.title, table))
        else:
            step_entry["content"] = content
            previous_outputs.append(f"### {step.title}\n{content}")

        step_results.append(step_entry)

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
        "table_columns": execution.metadata.get("table_columns", []),
        "table_schema": execution.metadata.get("table_schema", {}),
    }


# ---------------------------------------------------------------------------
# Backwards-compatible private aliases (kept for existing tests/imports)
# ---------------------------------------------------------------------------

_coerce_table_output = coerce_table_output
_normalize_table_cell_value = normalize_table_cell_value


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
