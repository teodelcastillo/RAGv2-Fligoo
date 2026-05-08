from __future__ import annotations

import logging
import os
import re
from typing import List

from django.db.models import QuerySet

from apps.chat.models import ChatMessage, ChatSession, MessageRole
from apps.chat.services.copilot_tools import (
    COPILOT_TOOLS,
    CopilotToolContext,
    execute_copilot_tool,
)
from apps.document.models import Document
from apps.document.utils.client_openia import generate_with_tools
from apps.project.models import Project, ProjectSection

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = int(os.environ.get("COPILOT_HISTORY_MESSAGES", "20"))

# Delimiters used to wrap draft content the consultant can insert into the
# editor as a clean section body. The optional `section=N` attribute lets the
# model bind the draft to a specific ProjectSection.position.
DRAFT_OPEN_PATTERN = re.compile(
    r"<<<DRAFT(?:\s+section=(?P<position>\d+))?>>>",
    flags=re.IGNORECASE,
)
DRAFT_CLOSE_TOKEN = "<<<END>>>"


# ---------------------------------------------------------------------------
# Document resolver for project context
# ---------------------------------------------------------------------------

def _resolve_project_documents(project: Project) -> QuerySet[Document]:
    from apps.project.models import ProjectDocument

    doc_ids = (
        ProjectDocument.objects
        .filter(project_id=project.id)
        .values_list("document_id", flat=True)
    )
    return Document.objects.filter(id__in=doc_ids)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _format_context_notes(context_notes: dict) -> str:
    if not context_notes:
        return ""
    lines = ["## Contexto del proyecto"]
    for key, value in context_notes.items():
        if value:
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def _format_project_structure(project: Project) -> str:
    sections = list(
        ProjectSection.objects.filter(project=project).order_by("position")
    )
    if not sections:
        return ""

    status_labels = {
        "not_started": "PENDIENTE",
        "in_progress": "EN PROGRESO",
        "review": "EN REVISION",
        "completed": "COMPLETADO",
    }

    template_name = ""
    if project.structure_template:
        template_name = f' "{project.structure_template.name}"'

    lines = [f"## Estructura del proyecto{template_name}"]
    for s in sections:
        label = status_labels.get(s.status, s.status.upper())
        line = f"{s.position}. [{label}] {s.title}"
        if s.description:
            line += f" — {s.description}"
        if s.notes:
            line += f" (Notas: {s.notes})"
        lines.append(line)
    return "\n".join(lines)


def _format_document_list(
    documents: QuerySet[Document],
    *,
    blueprint_slug: str | None = None,
) -> str:
    docs = list(documents.only("name", "slug"))
    if not docs:
        return "## Documentos disponibles\nNo hay documentos en el proyecto."
    lines = [f"## Documentos disponibles ({len(docs)})"]
    for doc in docs:
        marker = " [BLUEPRINT]" if blueprint_slug and doc.slug == blueprint_slug else ""
        lines.append(f"- [{doc.slug}]{marker} {doc.name}")
    return "\n".join(lines)


def build_copilot_system_prompt(
    project: Project,
    documents: QuerySet[Document],
) -> str:
    parts = [
        (
            f'Eres el Copiloto Ecofilia, un asistente experto en sostenibilidad que guia '
            f'al consultor a traves del proyecto "{project.name}".\n\n'
            "Tu rol:\n"
            "- Propones y sugieres, pero el consultor dirige.\n"
            "- Cuando el consultor pida avanzar, sugiere la siguiente seccion pendiente.\n"
            "- Puedes buscar en los documentos del proyecto, ejecutar analisis (skills), "
            "y calcular emisiones usando tus herramientas.\n"
            "- Cita siempre las fuentes de los documentos cuando uses informacion de ellos.\n"
            "- Responde en espanol a menos que el consultor use otro idioma."
        ),
        (
            "## Borradores para el documento final\n"
            "Cuando produzcas contenido pensado para INSERTAR en el documento entregable, "
            "envuelvelo entre los delimitadores <<<DRAFT>>> y <<<END>>>. Si el borrador "
            "corresponde a una seccion concreta de la estructura, indica la posicion en la "
            "etiqueta de apertura: <<<DRAFT section=N>>>. Solo el contenido entre delimitadores "
            "se insertara como cuerpo del entregable: usa Markdown (titulos con #, listas, "
            "negritas, etc.) y omite frases conversacionales como 'aqui tienes' o 'espero que "
            "te sirva'. Fuera de los delimitadores se breve, conversacional y orientado a "
            "siguiente paso. Si el consultor pide solo una idea o discusion, no uses los "
            "delimitadores."
        ),
    ]

    context_notes_block = _format_context_notes(project.context_notes or {})
    if context_notes_block:
        parts.append(context_notes_block)

    structure_block = _format_project_structure(project)
    if structure_block:
        parts.append(structure_block)

    blueprint_slug = (
        project.blueprint_document.slug if project.blueprint_document_id else None
    )
    doc_list_block = _format_document_list(documents, blueprint_slug=blueprint_slug)
    parts.append(doc_list_block)

    if blueprint_slug:
        parts.append(
            "## Documento principal (blueprint)\n"
            f"El blueprint del proyecto es '{blueprint_slug}'. Tratalo como mandato del "
            "encargo: las decisiones del entregable deben respetar lo definido alli, y "
            "cuando hagas afirmaciones del proyecto cita primero el blueprint cuando aplique."
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Message composition
# ---------------------------------------------------------------------------

def build_copilot_messages(
    session: ChatSession,
    user_content: str,
    project: Project,
    documents: QuerySet[Document],
    *,
    max_history: int = MAX_HISTORY_MESSAGES,
) -> list[dict]:
    system_prompt = build_copilot_system_prompt(project, documents)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    history_qs = (
        session.messages.order_by("-created_at")
        .exclude(role=MessageRole.SYSTEM)[:max_history]
    )
    history_messages = [
        {"role": str(msg.role), "content": msg.content or ""}
        for msg in reversed(list(history_qs))
    ]
    messages.extend(history_messages)

    messages.append({"role": "user", "content": user_content})
    return messages


# ---------------------------------------------------------------------------
# Draft extraction
# ---------------------------------------------------------------------------

def extract_draft_block(text: str) -> tuple[str | None, int | None]:
    """
    Pull the first ``<<<DRAFT[ section=N]>>> ... <<<END>>>`` block out of the
    assistant reply. Returns ``(draft_markdown, section_position)`` where each
    field is ``None`` when missing. Whitespace around the block is trimmed.
    """
    if not text:
        return None, None

    match = DRAFT_OPEN_PATTERN.search(text)
    if not match:
        return None, None

    body_start = match.end()
    end_idx = text.find(DRAFT_CLOSE_TOKEN, body_start)
    if end_idx == -1:
        return None, None

    body = text[body_start:end_idx].strip("\n").strip()
    if not body:
        return None, None

    position_str = match.group("position")
    position = int(position_str) if position_str else None
    return body, position


# ---------------------------------------------------------------------------
# Main copilot message processor
# ---------------------------------------------------------------------------

def process_copilot_message(
    session: ChatSession,
    user_content: str,
    user,
) -> tuple[str, dict, list[int]]:
    """
    Process a copilot message through the tool-calling loop.

    Returns (response_text, metadata, chunk_ids).
    """
    project = session.project
    if project is None:
        raise ValueError("Copilot sessions require a project context.")

    documents = _resolve_project_documents(project)

    messages = build_copilot_messages(
        session, user_content, project, documents,
    )

    tool_ctx = CopilotToolContext(
        user=user,
        project=project,
        allowed_documents=documents,
    )

    def _tool_executor(name: str, args_json: str) -> str:
        return execute_copilot_tool(name, args_json, tool_ctx)

    model = session.model
    temperature = session.temperature

    response_text, usage = generate_with_tools(
        messages,
        tools=COPILOT_TOOLS,
        tool_executor=_tool_executor,
        model=model,
        temperature=temperature,
    )

    chunk_ids = [c.id for c in tool_ctx.additional_chunks if hasattr(c, "id")]

    draft_markdown, draft_section_position = extract_draft_block(response_text)

    metadata: dict = {
        "usage": usage,
        "copilot": True,
        "tools_used": len(tool_ctx.additional_chunks) > 0,
        "chunks_retrieved": len(tool_ctx.additional_chunks),
    }
    if draft_markdown is not None:
        metadata["draft_markdown"] = draft_markdown
        metadata["draft_section_position"] = draft_section_position
        # Persist a snapshot on the section so the structure tab can show progress.
        if draft_section_position is not None:
            try:
                section = ProjectSection.objects.get(
                    project=project, position=draft_section_position,
                )
            except ProjectSection.DoesNotExist:
                pass
            else:
                section.output_snapshot = draft_markdown
                section.save(update_fields=["output_snapshot", "updated_at"])

    return response_text, metadata, chunk_ids


# ---------------------------------------------------------------------------
# Initialize project structure from template
# ---------------------------------------------------------------------------

def initialize_project_structure(project: Project, template_slug: str) -> list[ProjectSection]:
    from apps.project.models import ProjectStructureTemplate

    template = ProjectStructureTemplate.objects.get(slug=template_slug)

    ProjectSection.objects.filter(project=project).delete()

    project.structure_template = template
    project.save(update_fields=["structure_template"])

    sections = []
    for ts in template.sections.order_by("position"):
        section = ProjectSection.objects.create(
            project=project,
            template_section=ts,
            title=ts.title,
            description=ts.description,
            position=ts.position,
        )
        sections.append(section)

    return sections
