from __future__ import annotations

import logging
import os
from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple

from django.db import transaction
from django.db.models import Q, QuerySet
from rest_framework.exceptions import APIException

from apps.chat.models import ChatMessage, ChatSession, MessageRole
from apps.document.models import Document, SmartChunk
from apps.document.services import accessible_documents_queryset
from apps.document.utils.client_openia import generate_chat_completion

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHUNKS = int(os.environ.get("CHAT_CONTEXT_CHUNKS", "4"))
MAX_HISTORY_MESSAGES = int(os.environ.get("CHAT_HISTORY_MESSAGES", "10"))


def fetch_relevant_chunks(
    *,
    user,
    query_text: str,
    allowed_documents: QuerySet[Document],
    top_n: int | None = None,
    topics: List[str] | None = None,
    max_chunks_per_doc: int | None = None,
) -> List[SmartChunk]:
    """
    Returns the most relevant chunks limited to the allowed documents for the session.

    Args:
        user: Django user performing the query (used for permission filtering).
        query_text: Natural language query to search similar chunks.
        allowed_documents: Queryset of documents allowed in the session.
        top_n: Maximum number of chunks to return (default: MAX_CONTEXT_CHUNKS).
        topics: Optional list of keywords/topics to filter chunks by SmartChunk.keywords.
        max_chunks_per_doc: Optional hard limit of chunks per document in the final result.
    """
    top_n = top_n or MAX_CONTEXT_CHUNKS

    if not query_text:
        return []

    doc_ids = list(allowed_documents.values_list("id", flat=True))
    if not doc_ids:
        return []

    qs = SmartChunk.objects.filter(document_id__in=doc_ids)
    if not user.is_staff:
        # Incluir chunks de documentos propios, públicos, compartidos y de proyectos compartidos
        from apps.project.models import ProjectShare

        shared_project_ids = ProjectShare.objects.filter(
            user=user
        ).values_list("project_id", flat=True)
        qs = qs.filter(
            Q(document__owner=user)
            | Q(document__is_public=True)
            | Q(document__shares__user=user)
            | Q(document__projects__id__in=shared_project_ids)
        ).distinct()

    # Filtro temático opcional usando SmartChunk.keywords
    if topics:
        normalized_topics = [t.strip().lower() for t in topics if t and t.strip()]
        if normalized_topics:
            qs = qs.filter(keywords__overlap=normalized_topics)

    # Recuperar los chunks más similares por embedding
    similar_chunks = list(qs.top_similar(query_text, top_n=top_n))

    if max_chunks_per_doc is None or max_chunks_per_doc <= 0:
        return similar_chunks

    # Post-procesar para limitar el número de chunks por documento
    per_doc_counts: dict[int, int] = {}
    balanced: List[SmartChunk] = []
    for chunk in similar_chunks:
        doc_id = chunk.document_id
        current = per_doc_counts.get(doc_id, 0)
        if current >= max_chunks_per_doc:
            continue
        per_doc_counts[doc_id] = current + 1
        balanced.append(chunk)

    return balanced


def build_context_block(chunks: Iterable[SmartChunk]) -> str:
    sections = []
    for chunk in chunks:
        sections.append(
            (
                f"Fuente: {chunk.document.name} (slug: {chunk.document.slug}, "
                f"chunk #{chunk.chunk_index})\n{chunk.content.strip()}"
            )
        )
    return "\n\n".join(sections).strip()


def suggest_related_documents(
    user,
    query_text: str,
    session: ChatSession,
    top_n_chunks: int = 20,
    max_recommendations: int = 5,
) -> List[Dict[str, Any]]:
    """
    Sugiere documentos relevantes que NO están ya en la sesión.
    Usa fetch_relevant_chunks para encontrar chunks similares, luego agrupa por documento.
    
    Args:
        user: Django user performing the query.
        query_text: Natural language query to find related documents.
        session: ChatSession to exclude its already assigned documents.
        top_n_chunks: Number of chunks to retrieve for recommendation (default: 20).
        max_recommendations: Maximum number of documents to recommend (default: 5).
    
    Returns:
        List of dicts with keys: id, slug, name, relevance_score
    """
    # Documentos ya asociados a la sesión
    current_doc_ids = list(session.allowed_documents.values_list("id", flat=True))

    # Todos los accesibles, excluyendo los ya en la sesión
    all_accessible = accessible_documents_queryset(user)
    candidate_docs = all_accessible.exclude(id__in=current_doc_ids)

    if not query_text or not candidate_docs.exists():
        return []

    # Usar fetch_relevant_chunks para encontrar chunks relevantes
    # Con top_n más alto para tener más opciones de documentos
    relevant_chunks = fetch_relevant_chunks(
        user=user,
        query_text=query_text,
        allowed_documents=candidate_docs,
        top_n=top_n_chunks,
    )

    if not relevant_chunks:
        return []

    # Contar cuántos chunks relevantes tiene cada documento
    doc_counts = Counter(chunk.document_id for chunk in relevant_chunks)

    # Obtener los documentos más representados
    top_doc_ids = [doc_id for doc_id, _ in doc_counts.most_common(max_recommendations)]

    # Cargar documentos con sus slugs
    docs = Document.objects.filter(id__in=top_doc_ids)
    doc_by_id = {d.id: d for d in docs}

    recommendations = []
    for doc_id in top_doc_ids:
        doc = doc_by_id.get(doc_id)
        if not doc:
            continue
        # Incluir el "score" (número de chunks relevantes)
        recommendations.append(
            {
                "id": doc.id,
                "slug": doc.slug,
                "name": doc.name,
                "relevance_score": doc_counts[doc_id],
            }
        )

    return recommendations


def run_single_step_chat(
    *,
    user,
    session: ChatSession,
    content: str,
) -> Tuple[ChatMessage, ChatMessage]:
    """
    Ejecuta el flujo actual de chat de un solo paso (RAG + LLM) y devuelve
    el mensaje de usuario y el de asistente creados.
    
    Si la sesión no tiene documentos asignados, usa RAG global sobre toda
    la biblioteca accesible del usuario.
    """
    allowed_docs = session.allowed_documents.all()
    
    # Si no hay documentos asignados, usar RAG global sobre toda la biblioteca accesible
    if not allowed_docs.exists():
        allowed_docs = accessible_documents_queryset(user)
    
    chunks: List[SmartChunk] = []
    context_block: str | None = None

    # Buscar chunks relevantes (usando RAG global o focalizado según corresponda)
    if allowed_docs.exists():
        chunks = fetch_relevant_chunks(
            user=user,
            query_text=content,
            allowed_documents=allowed_docs,
        )
        context_block = build_context_block(chunks)

    # Construir mensajes base
    base_messages = [
        {"role": MessageRole.SYSTEM, "content": session.system_prompt.strip()},
    ]

    # Si hay contexto de documentos, agregarlo con prioridad
    if context_block:
        base_messages.append(
            {
                "role": MessageRole.SYSTEM,
                "content": (
                    "Utiliza exclusivamente el siguiente contexto para responder. "
                    "Si no hay suficiente información en el contexto, responde que no se encontró."
                    f"\n\n{context_block}"
                ),
            }
        )

    history_qs = (
        session.messages.order_by("-created_at")
        .exclude(role=MessageRole.SYSTEM)
        [:MAX_HISTORY_MESSAGES]
    )
    history_messages = [
        {"role": message.role, "content": message.content}
        for message in reversed(list(history_qs))
    ]
    messages = base_messages + history_messages
    messages.append({"role": MessageRole.USER, "content": content})

    with transaction.atomic():
        user_message = ChatMessage.objects.create(
            session=session,
            role=MessageRole.USER,
            content=content,
        )

        try:
            answer_text, usage = generate_chat_completion(
                messages,
                model=session.model,
                temperature=session.temperature,
            )
        except Exception as exc:  # pragma: no cover - network failure
            error_msg = str(exc)
            logger.exception("Error al generar respuesta de OpenAI: %s", error_msg)
            # Provide more specific error messages for common issues
            lower_error = error_msg.lower()
            if "api_key" in lower_error or "authentication" in lower_error:
                raise APIException(
                    "Error de autenticación con OpenAI. Verifica la configuración de la API key."
                ) from exc
            if "rate limit" in lower_error or "quota" in lower_error:
                raise APIException(
                    "Límite de tasa excedido. Por favor, intenta de nuevo en unos momentos."
                ) from exc
            if "model" in lower_error:
                raise APIException(
                    f"Error con el modelo de OpenAI: {error_msg}"
                ) from exc
            raise APIException(
                f"No fue posible generar la respuesta en este momento: {error_msg}"
            ) from exc

        chunk_ids = [chunk.id for chunk in chunks]
        
        # Generar recomendaciones de documentos complementarios
        recommended_docs = suggest_related_documents(
            user=user,
            query_text=content,
            session=session,
        )
        
        metadata = {"usage": usage}
        if recommended_docs:
            metadata["recommended_documents"] = recommended_docs
        
        assistant_message = ChatMessage.objects.create(
            session=session,
            role=MessageRole.ASSISTANT,
            content=answer_text,
            chunk_ids=chunk_ids,
            metadata=metadata,
        )

    return user_message, assistant_message

