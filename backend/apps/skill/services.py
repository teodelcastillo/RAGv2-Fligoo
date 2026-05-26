from __future__ import annotations

import json
import logging
import os
from typing import List

from django.db.models import QuerySet
from django.utils import timezone

from apps.chat.services.rag import build_context_block, fetch_relevant_chunks
from apps.document.models import Document
from apps.document.utils.client_openia import generate_chat_completion, generate_with_tools
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


class StepAwaitingApproval(Exception):
    """
    Raised by _run_copilot when a step with approval_required=True has been
    completed and persisted. The runner catches this and sets status=AWAITING_APPROVAL
    instead of FAILED.
    """

DEFAULT_CHUNKS = int(os.environ.get("SKILL_CONTEXT_CHUNKS", "6"))

# Maximum chunks assembled from the research phase scratchpad.
RESEARCH_SCRATCHPAD_MAX_CHUNKS = int(os.environ.get("SKILL_RESEARCH_SCRATCHPAD_CHUNKS", "20"))
# Maximum distinct research queries derived automatically from step instructions.
RESEARCH_AUTO_QUERIES_MAX = int(os.environ.get("SKILL_RESEARCH_AUTO_QUERIES", "8"))


# ---------------------------------------------------------------------------
# Document resolver
# ---------------------------------------------------------------------------

def resolve_documents(execution: SkillExecution) -> QuerySet[Document]:
    """
    Returns the queryset of documents available for this execution context.
    - Repository: only is_active=True documents
    - Project: all linked documents
    - Document: the single document

    When ``execution.metadata["document_slugs_filter"]`` contains slugs, the
    base context queryset is intersected with that selection so the run only
    sees the documents the user explicitly chose. An empty/absent filter
    preserves the legacy behaviour of using the full context.
    """
    metadata = execution.metadata or {}
    slug_filter = (
        metadata.get("document_slugs_filter")
        or execution.skill.pinned_document_slugs
        or []
    )
    slug_filter = [s for s in slug_filter if isinstance(s, str) and s.strip()]

    if execution.repository_id:
        from apps.repository.models import RepositoryDocument
        doc_ids = (
            RepositoryDocument.objects
            .filter(repository_id=execution.repository_id, is_active=True)
            .values_list("document_id", flat=True)
        )
        qs = Document.objects.filter(id__in=doc_ids)
        if slug_filter:
            qs = qs.filter(slug__in=slug_filter)
        return qs

    if execution.project_id:
        from apps.project.models import ProjectDocument
        doc_ids = (
            ProjectDocument.objects
            .filter(project_id=execution.project_id)
            .values_list("document_id", flat=True)
        )
        qs = Document.objects.filter(id__in=doc_ids)
        if slug_filter:
            qs = qs.filter(slug__in=slug_filter)
        return qs

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

def _render_prompt_variables(
    template: str,
    *,
    context_block: str,
    extra_instructions: str,
    input_values: dict,
) -> str:
    """
    Replace all template tokens in ``template``.

    Token resolution order:
    1. {{context}}            — RAG context block.
    2. {{extra_instructions}} — free-text user override.
    3. {{key}}                — typed SkillParameter values from input_values.
    """
    result = template
    result = result.replace("{{context}}", context_block or "(No document content found)")
    result = result.replace("{{extra_instructions}}", extra_instructions or "")
    for key, value in (input_values or {}).items():
        result = result.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")
    return result.strip()


# Backward-compatible wrapper used by existing tests.
def _render_quick_prompt(template: str, context_block: str, extra_instructions: str) -> str:
    return _render_prompt_variables(
        template,
        context_block=context_block,
        extra_instructions=extra_instructions,
        input_values={},
    )


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
# Tool-aware completion helper
# ---------------------------------------------------------------------------

def _call_model(
    messages: list[dict],
    *,
    skill,
    tool_ctx=None,
) -> tuple[str, dict]:
    """
    Dispatch to generate_with_tools or generate_chat_completion depending on
    whether the skill has tools_enabled and a valid tool context is provided.
    """
    if skill.tools_enabled and tool_ctx is not None:
        from apps.skill.tools import ALL_TOOLS, execute_tool

        def _executor(name: str, args_json: str) -> str:
            return execute_tool(name, args_json, tool_ctx)

        return generate_with_tools(
            messages,
            tools=ALL_TOOLS,
            tool_executor=_executor,
            model=skill.model,
            temperature=skill.temperature,
        )
    return generate_chat_completion(
        messages, model=skill.model, temperature=skill.temperature
    )


# ---------------------------------------------------------------------------
# Research phase  (Sprint 2A)
# ---------------------------------------------------------------------------

def _run_research_phase(
    *,
    execution: SkillExecution,
    skill,
    documents: QuerySet[Document],
    steps: List[SkillStep],
) -> tuple[str, list]:
    """
    Execute a broad retrieval pass before the authoring steps.

    Returns:
        (scratchpad_block, chunks_used)
        - scratchpad_block: formatted context string injected into each step.
        - chunks_used: list of SmartChunk objects for source tracking.
    """
    research_queries: list[str] = list(skill.research_queries or [])

    if not research_queries:
        # Auto-derive from step instructions, deduplicating by truncated content.
        seen: set[str] = set()
        for step in steps:
            q = f"{step.title}. {step.instructions}"[:200].strip()
            if q and q not in seen:
                seen.add(q)
                research_queries.append(q)
            if len(research_queries) >= RESEARCH_AUTO_QUERIES_MAX:
                break

    all_chunks: list = []
    seen_ids: set[int] = set()

    for query in research_queries[:RESEARCH_AUTO_QUERIES_MAX]:
        try:
            chunks = fetch_relevant_chunks(
                user=execution.owner,
                query_text=query,
                allowed_documents=documents,
                top_n=4,
                retrieval_strategy="hybrid_per_document",
                k_per_doc=2,
                total_limit=8,
            )
        except Exception as exc:
            logger.warning("Research phase query %r failed: %s", query, exc)
            continue

        for c in chunks:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                all_chunks.append(c)

    capped = all_chunks[:RESEARCH_SCRATCHPAD_MAX_CHUNKS]
    if not capped:
        return "", []

    return build_context_block(capped), capped


# ---------------------------------------------------------------------------
# Quick skill runner
# ---------------------------------------------------------------------------

def _run_quick(execution: SkillExecution, documents: QuerySet[Document]) -> None:
    from apps.skill.tools import SkillToolContext

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

    prompt = _render_prompt_variables(
        skill.prompt_template,
        context_block=context_block,
        extra_instructions=execution.extra_instructions,
        input_values=execution.input_values,
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

    tool_ctx = SkillToolContext(user=execution.owner, allowed_documents=documents)
    output_text, usage = _call_model(messages, skill=skill, tool_ctx=tool_ctx)
    all_chunks = chunks + tool_ctx.additional_chunks

    if is_table:
        parsed = coerce_table_output(output_text=output_text, table_schema=table_schema)
        execution.output = ""
        execution.output_structured = parsed
    else:
        execution.output = output_text
        execution.output_structured = {}

    source_stats = _collect_source_stats(all_chunks, total_docs=documents.count())
    execution.metadata = {
        "usage": usage,
        "chunks_used": len(all_chunks),
        "tool_calls_made": len(tool_ctx.additional_chunks) > 0,
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
            for c in all_chunks
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


def _rebuild_previous_outputs(step_results: list[dict]) -> List[str]:
    """
    Reconstruct the previous_outputs list from already-completed step entries.
    Used when resuming a paused execution so context is preserved for later steps.
    """
    previous_outputs: List[str] = []
    for entry in step_results:
        title = entry.get("title", "")
        if entry.get("output_mode") == ExecutionOutputMode.TABLE and "table" in entry:
            previous_outputs.append(_table_summary_for_history(title, entry["table"]))
        else:
            previous_outputs.append(f"### {title}\n{entry.get('content', '')}")
    return previous_outputs


def _run_copilot(execution: SkillExecution, documents: QuerySet[Document]) -> None:
    from apps.skill.tools import SkillToolContext

    skill = execution.skill
    steps: List[SkillStep] = list(skill.steps.all())
    if not steps:
        raise ValueError("This Copilot skill has no steps defined.")

    # Resume: load any steps already completed in a previous run segment.
    already_done: list[dict] = list(
        (execution.output_structured or {}).get("steps", [])
    )
    resume_from_position = len(already_done)

    step_results: list[dict] = list(already_done)
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    # Rebuild conversation context from completed steps so later steps have full history.
    previous_outputs: List[str] = _rebuild_previous_outputs(already_done)
    all_step_chunks: list = []
    effective_retrieval_strategy = (
        RetrievalStrategy.HYBRID_PER_DOCUMENT
        if skill.comparative_mode_enabled
        else skill.retrieval_strategy
    )

    # ------------------------------------------------------------------ #
    # Research phase (Sprint 2A)                                          #
    # ------------------------------------------------------------------ #
    shared_scratchpad = ""
    if skill.research_phase_enabled:
        shared_scratchpad, research_chunks = _run_research_phase(
            execution=execution,
            skill=skill,
            documents=documents,
            steps=steps,
        )
        all_step_chunks.extend(research_chunks)
        logger.debug(
            "Research phase for execution %s: %d chunks collected.",
            execution.id,
            len(research_chunks),
        )

    for step_index, step in enumerate(steps):
        # Skip steps already completed in a prior run segment (resume support).
        if step_index < resume_from_position:
            continue

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
        # Inject typed parameter values as a context note
        if execution.input_values:
            param_lines = [
                f"- {k}: {v}"
                for k, v in execution.input_values.items()
                if v not in (None, "")
            ]
            if param_lines:
                lines.append("\n## Run parameters:\n" + "\n".join(param_lines))

        if execution.extra_instructions:
            lines.append(f"\nAdditional instructions from user: {execution.extra_instructions}")
        if previous_outputs:
            lines.append("\n## Previous sections already written:")
            for prev in previous_outputs:
                lines.append(prev)
        # Shared research scratchpad (Sprint 2A)
        if shared_scratchpad:
            lines.append(f"\n## Research scratchpad (broad corpus overview):\n{shared_scratchpad}")
        if context_block:
            lines.append(f"\n## Document context (targeted for this section):\n{context_block}")
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

        tool_ctx = SkillToolContext(user=execution.owner, allowed_documents=documents)
        content, usage = _call_model(messages, skill=skill, tool_ctx=tool_ctx)
        all_step_chunks.extend(tool_ctx.additional_chunks)

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

        # Persist this step immediately (Sprint 3: incremental output for polling).
        execution.output_structured = {"steps": step_results}
        execution.steps_completed = len(step_results)
        execution.save(update_fields=["output_structured", "steps_completed"])

        # Sprint 4: if this step requires human approval, pause the run here.
        if step.approval_required:
            execution.current_step_position = step.position
            execution.save(update_fields=["current_step_position"])
            raise StepAwaitingApproval(
                f"Step '{step.title}' (position {step.position}) is awaiting approval."
            )

    # Final metadata written once all steps complete.
    execution.output_structured = {"steps": step_results}
    source_stats = _collect_source_stats(all_step_chunks, total_docs=documents.count())
    execution.metadata = {
        "usage": total_usage,
        "research_phase_enabled": skill.research_phase_enabled,
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

        if execution.status not in (
            ExecutionStatus.PENDING,
            ExecutionStatus.FAILED,
            ExecutionStatus.AWAITING_APPROVAL,
        ):
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
            execution.current_step_position = None
        except StepAwaitingApproval:
            # Not a failure — the run is intentionally paused.
            execution.status = ExecutionStatus.AWAITING_APPROVAL
        except Exception as exc:
            logger.exception("SkillExecution %s failed", execution.id)
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(exc)
        finally:
            execution.finished_at = timezone.now()
            # For copilot runs, output_structured was already persisted incrementally
            # per step — avoid a redundant final save of that field.
            if execution.skill.skill_type == SkillType.QUICK:
                execution.save(update_fields=[
                    "status", "output", "output_structured", "metadata",
                    "error_message", "finished_at", "current_step_position",
                ])
            else:
                execution.save(update_fields=[
                    "status", "metadata", "error_message",
                    "finished_at", "current_step_position",
                ])

        return execution


def execution_to_markdown(execution: SkillExecution) -> str:
    """Return the best available markdown representation of a skill execution."""
    if execution.edited_output and execution.edited_output.strip():
        return execution.edited_output.strip()

    if execution.skill.skill_type == SkillType.QUICK:
        if execution.output_mode == ExecutionOutputMode.TABLE:
            structured = execution.output_structured or {}
            columns = structured.get("columns") or []
            rows = structured.get("rows") or []
            if not columns:
                return execution.output or ""
            header = "| " + " | ".join(str(c) for c in columns) + " |"
            separator = "| " + " | ".join("---" for _ in columns) + " |"
            body = []
            for row in rows:
                if isinstance(row, dict):
                    body.append(
                        "| "
                        + " | ".join(str(row.get(col, "")) for col in columns)
                        + " |"
                    )
            return "\n".join([header, separator, *body])
        return execution.output or ""

    steps = (execution.output_structured or {}).get("steps") or []
    parts = []
    for step in steps:
        title = step.get("title") or "Step"
        if step.get("output_mode") == "table" and step.get("table"):
            table = step["table"]
            columns = table.get("columns") or []
            rows = table.get("rows") or []
            if columns:
                header = "| " + " | ".join(str(c) for c in columns) + " |"
                separator = "| " + " | ".join("---" for _ in columns) + " |"
                body = []
                for row in rows:
                    if isinstance(row, dict):
                        body.append(
                            "| "
                            + " | ".join(str(row.get(col, "")) for col in columns)
                            + " |"
                        )
                parts.append(f"## {title}\n\n" + "\n".join([header, separator, *body]))
            else:
                parts.append(f"## {title}\n\n{step.get('content') or ''}")
        else:
            parts.append(f"## {title}\n\n{step.get('content') or ''}")
    return "\n\n---\n\n".join(parts)


def execute_skill(execution: SkillExecution) -> SkillExecution:
    return SkillRunner().run(execution.id)


# ---------------------------------------------------------------------------
# Sprint 4 — Human-in-the-loop helpers
# ---------------------------------------------------------------------------

def approve_step(execution: SkillExecution, *, override_content: str | None = None) -> SkillExecution:
    """
    Approve the current awaiting step and continue the run.

    If ``override_content`` is provided the last completed step's text content
    is replaced before the run resumes. This lets the consultant edit the output
    and have subsequent steps use the corrected version as context.

    Returns the execution object (status will be PENDING until the async task
    picks it up and starts running again).
    """
    if execution.status != ExecutionStatus.AWAITING_APPROVAL:
        raise ValueError(
            f"Cannot approve: execution {execution.id} is not awaiting approval "
            f"(current status: {execution.status})."
        )

    if override_content is not None:
        steps = list((execution.output_structured or {}).get("steps", []))
        if steps:
            last = dict(steps[-1])
            # Only override text steps — table steps are left as-is.
            if last.get("output_mode") != ExecutionOutputMode.TABLE:
                last["content"] = override_content
                last["human_edited"] = True
                steps[-1] = last
                execution.output_structured = {"steps": steps}

    execution.status = ExecutionStatus.PENDING
    execution.error_message = ""
    execution.save(update_fields=["status", "output_structured", "error_message"])
    return execution


def regenerate_step(execution: SkillExecution) -> SkillExecution:
    """
    Discard the last completed step and re-run it.

    Strips the last step from output_structured, decrements steps_completed,
    and resets status to PENDING so the Celery task re-runs from that step.
    """
    if execution.status != ExecutionStatus.AWAITING_APPROVAL:
        raise ValueError(
            f"Cannot regenerate: execution {execution.id} is not awaiting approval "
            f"(current status: {execution.status})."
        )

    steps = list((execution.output_structured or {}).get("steps", []))
    if steps:
        steps.pop()
    execution.output_structured = {"steps": steps}
    execution.steps_completed = max(0, execution.steps_completed - 1)
    execution.status = ExecutionStatus.PENDING
    execution.current_step_position = None
    execution.error_message = ""
    execution.save(update_fields=[
        "status", "output_structured", "steps_completed",
        "current_step_position", "error_message",
    ])
    return execution
