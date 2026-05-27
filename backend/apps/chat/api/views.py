from __future__ import annotations

import json
import logging
import os

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import StreamingHttpResponse
from rest_framework import mixins, status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.api.serializers import (
    ChatMessageCreateSerializer,
    ChatMessageSerializer,
    ChatSessionCreateSerializer,
    ChatSessionSerializer,
    prefetch_chunks_by_id,
)
from apps.chat.models import ChatMessage, ChatSession, MessageRole, touch_chat_session_activity
from apps.chat.services.context_builder import build_citation_prompt
from apps.chat.services.query_analysis import (
    COVERAGE_MODE_ALL,
    apply_response_mode_override,
    classify_query_hybrid,
    contextualize_query,
)
from apps.chat.services.rag import RetrievalResult, retrieve_for_chat, suggest_related_library_documents
from apps.document.models import Document
from apps.document.utils import client_openia

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = int(os.environ.get("CHAT_HISTORY_MESSAGES", "10"))


def _chat_retrieval_params(
    session: ChatSession,
    content: str,
    response_mode: str | None = None,
) -> dict:
    """
    Heuristic sizing for the RAG retrieval pool given the session scope and
    the current message. Wider pools for broader questions and bigger libraries.
    """
    doc_count = session.allowed_documents.count()
    analysis = classify_query_hybrid(content)
    # Apply the same override the RAG pipeline uses so pool sizing
    # matches the eventual retrieval decision.
    analysis = apply_response_mode_override(analysis, response_mode)
    broad_question = len((content or "").split()) >= 18
    if analysis.coverage_mode == COVERAGE_MODE_ALL:
        total_limit = doc_count
        max_chunks_per_doc = 1
    elif doc_count == 1:
        # Single-document chat: retrieve more chunks for richer context
        total_limit = 10
        max_chunks_per_doc = 10
    else:
        total_limit = min(18, max(8, doc_count * 2))
        max_chunks_per_doc = 2
    if not broad_question and analysis.coverage_mode != COVERAGE_MODE_ALL and doc_count > 1:
        total_limit = min(total_limit, 12)
    return {
        "top_n": total_limit,
        "total_limit": total_limit,
        "k_per_doc": max_chunks_per_doc,
        "max_chunks_per_doc": max_chunks_per_doc,
    }


def _build_coverage_instruction(session: ChatSession, retrieval: RetrievalResult) -> str:
    if retrieval.analysis is None or retrieval.analysis.coverage_mode != COVERAGE_MODE_ALL:
        return ""

    docs = list(session.allowed_documents.order_by("name").values("id", "name", "slug"))
    total_docs = len(docs)
    covered_ids = retrieval.covered_document_ids
    missing = [doc for doc in docs if doc["id"] not in covered_ids]
    covered_count = total_docs - len(missing)
    missing_text = (
        " Documentos sin evidencia recuperada: "
        + ", ".join(f"{doc['name']} ({doc['slug']})" for doc in missing)
        + "."
        if missing
        else ""
    )
    return (
        "\n\nPOLITICA DE COBERTURA OBLIGATORIA:\n"
        f"- La sesión tiene {total_docs} documentos seleccionados.\n"
        f"- El contexto recuperado cubre {covered_count}/{total_docs} documentos.\n"
        "- Para preguntas de panorama/repositorio/base documental, debes razonar "
        "sobre todos los documentos cubiertos y no presentar una respuesta como "
        "completa si falta cobertura.\n"
        "- Si el usuario pide listar o resumir por documento, devuelve exactamente "
        "una entrada por cada documento cubierto, sin repetir documentos.\n"
        "- Si hay documentos sin evidencia recuperada, menciónalos explícitamente "
        "como no cubiertos en esta respuesta."
        f"{missing_text}"
    )


def _workspace_session(session: ChatSession) -> bool:
    """Sesión ligada a proyecto o repositorio: tiene sentido sugerir docs de la biblioteca global."""
    return session.project_id is not None or session.repository_id is not None


def _run_retrieval(
    session: ChatSession,
    content: str,
    user,
    response_mode: str | None = None,
) -> RetrievalResult:
    """
    Defensive wrapper around ``retrieve_for_chat``. Failures (embeddings,
    pgvector, OpenAI keys) must not bubble up as 500s — return an empty
    result so the chat still answers using base knowledge.

    When the session has no explicitly attached documents (e.g. the global
    chat), falls back to the user's personal document library so that
    questions like "quién es Teodoro" can still be answered from the user's
    own uploaded CVs/reports.
    """
    allowed_docs = session.allowed_documents.all()
    if not allowed_docs.exists():
        # No documents pinned to this session → fall back to the user's
        # personal library (owned documents that have been fully processed).
        # We deliberately exclude public documents here to avoid polluting
        # a personal query with unrelated library content.
        from apps.document.models import ChunkingStatus
        personal_docs = (
            Document.objects.filter(
                owner=user,
                chunking_status=ChunkingStatus.DONE,
            )
            .filter(chunks__embedding__isnull=False)
            .distinct()
        )
        if not personal_docs.exists():
            return RetrievalResult()
        allowed_docs = personal_docs

    retrieval_query = content
    history_qs = (
        session.messages
        .exclude(role=MessageRole.SYSTEM)
        .order_by("-created_at")[:6]
    )
    history = [
        {"role": str(m.role), "content": m.content or ""}
        for m in reversed(list(history_qs))
    ]
    if history:
        retrieval_query = contextualize_query(content, history)

    try:
        result = retrieve_for_chat(
            user=user,
            query_text=retrieval_query,
            allowed_documents=allowed_docs,
            response_mode=response_mode,
            **_chat_retrieval_params(session, retrieval_query, response_mode=response_mode),
        )
        if _workspace_session(session):
            try:
                result.recommended_documents = suggest_related_library_documents(
                    user=user,
                    query_text=content,
                    exclude_document_ids=list(allowed_docs.values_list("id", flat=True)),
                )
            except Exception as rec_exc:
                logger.warning(
                    "Recomendaciones de biblioteca omitidas (session=%s): %s",
                    session.id,
                    rec_exc,
                )
        return result
    except Exception as exc:
        logger.exception("Chat RAG pipeline failed (session=%s): %s", session.id, exc)
        return RetrievalResult()


def _compose_messages(
    session: ChatSession,
    content: str,
    retrieval: RetrievalResult,
    response_mode: str | None = None,
    *,
    max_history: int = MAX_HISTORY_MESSAGES,
) -> list[dict]:
    """Build the OpenAI messages list (system + context + history + user)."""
    system_text = (session.system_prompt or "").strip() or (
        "Eres Ecofilia, un asistente útil. Responde de forma clara y concisa."
    )

    base_messages: list[dict] = [
        {"role": str(MessageRole.SYSTEM), "content": system_text},
    ]

    if retrieval.context_block:
        doc_count = session.allowed_documents.count()
        if doc_count == 1:
            single_doc = session.allowed_documents.first()
            doc_label = f'del documento "{single_doc.name}"' if single_doc else "del documento"
            context_preamble = (
                f"El siguiente contexto proviene {doc_label}. "
                "Este es el único documento en esta sesión. Todas las preguntas del usuario son sobre este documento exclusivamente. "
                "Basate en este contexto para responder con precisión. "
                "Si la información solicitada no aparece en el contexto, indícalo claramente. "
                "No hagas referencia a otros documentos ni a información que no esté en este contexto. "
            )
        else:
            context_preamble = (
                "El siguiente contexto proviene de los documentos del usuario. "
                "Prioriza este contexto para responder. "
                "Si la información del contexto es suficiente, basate principalmente en ella. "
                "Si el contexto no contiene información relevante o es insuficiente, "
                "puedes complementar con tu conocimiento general, pero indica claramente "
                "qué parte proviene del documento y qué parte de tu conocimiento general. "
            )
        base_messages.append(
            {
                "role": str(MessageRole.SYSTEM),
                "content": (
                    context_preamble
                    + build_citation_prompt()
                    + _build_coverage_instruction(session, retrieval)
                    + f"\n\n{retrieval.context_block}"
                ),
            }
        )

    history_qs = (
        session.messages.order_by("-created_at")
        .exclude(role=MessageRole.SYSTEM)[:max_history]
    )
    history_messages = [
        {"role": str(message.role), "content": message.content or ""}
        for message in reversed(list(history_qs))
    ]

    messages = base_messages + history_messages
    if response_mode:
        mode_instructions = {
            "tabla": (
                "Responde en formato tabla Markdown (GFM) cuando sea posible. "
                "Incluye encabezados claros y al menos 2 columnas. "
                "Si no hay datos suficientes para tabular, explicá brevemente por qué."
            ),
        }
        extra_instruction = mode_instructions.get(response_mode, "")
        messages.append(
            {
                "role": str(MessageRole.SYSTEM),
                "content": (
                    "El usuario seleccionó un modo de respuesta explícito. "
                    f"Prioriza este modo: '{response_mode}'."
                    + (f" {extra_instruction}" if extra_instruction else "")
                ),
            }
        )
    messages.append({"role": str(MessageRole.USER), "content": content})
    return messages


class ChatSessionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class ChatCompletionFailed(APIException):
    """OpenAI u otro fallo al generar respuesta — 503 para que el cliente reciba JSON con detail."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "No se pudo generar la respuesta del asistente."
    default_code = "chat_completion_failed"


class ChatSessionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatSessionSerializer
    pagination_class = ChatSessionPagination

    def get_queryset(self):
        qs = ChatSession.objects.prefetch_related("allowed_documents")
        if self.request.user.is_staff:
            base = qs
        else:
            base = qs.filter(owner=self.request.user)

        # Listado: no devolver sesiones vacías salvo ?include_empty=true (evita ruido y carga innecesaria).
        if getattr(self, "action", None) == "list":
            raw = (self.request.query_params.get("include_empty") or "").lower()
            if raw not in ("1", "true", "yes"):
                base = base.filter(
                    Exists(
                        ChatMessage.objects.filter(session_id=OuterRef("pk"))
                    )
                )
        return base.order_by("-updated_at", "-created_at", "-id")

    def get_serializer_class(self):
        if self.action == "create":
            return ChatSessionCreateSerializer
        return ChatSessionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save(owner=request.user)
        output = ChatSessionSerializer(
            session, context=self.get_serializer_context()
        )
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)


class ChatMessageViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatMessageSerializer

    def get_queryset(self):
        qs = ChatMessage.objects.select_related("session", "session__owner").order_by(
            "created_at"
        )
        if not self.request.user.is_staff:
            qs = qs.filter(session__owner=self.request.user)

        session_id = self.request.query_params.get("session")
        if session_id:
            qs = qs.filter(session_id=session_id)
        return qs

    def list(self, request, *args, **kwargs):
        session_id = request.query_params.get("session")
        if not session_id:
            return Response(
                {"detail": "El parámetro 'session' es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.filter_queryset(self.get_queryset())
        messages = list(queryset)

        all_chunk_ids: list[int] = []
        for message in messages:
            all_chunk_ids.extend(message.chunk_ids or [])

        serializer_context = self.get_serializer_context()
        serializer_context["include_chunk_content"] = False
        serializer_context["chunks_by_id"] = prefetch_chunks_by_id(
            all_chunk_ids,
            include_content=False,
        )
        serializer = self.get_serializer(
            messages,
            many=True,
            context=serializer_context,
        )
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = ChatMessageCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.validated_data["session"]
        content = serializer.validated_data["content"]
        document_slugs = serializer.validated_data.get("document_slugs")
        response_mode = serializer.validated_data.get("response_mode")

        _sync_session_documents_for_request(session, document_slugs)
        retrieval = _run_retrieval(session, content, request.user, response_mode=response_mode)
        messages = _compose_messages(
            session,
            content,
            retrieval,
            response_mode=response_mode,
        )

        with transaction.atomic():
            user_message = ChatMessage.objects.create(
                session=session,
                role=MessageRole.USER,
                content=content,
            )

            try:
                answer_text, usage = client_openia.generate_chat_completion(
                    messages,
                    model=session.model,
                    temperature=session.temperature,
                )
            except Exception as exc:  # pragma: no cover - network failure
                error_msg = str(exc)
                logger.exception("Error al generar respuesta de OpenAI: %s", error_msg)
                if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                    raise ChatCompletionFailed(
                        detail="Error de autenticación con OpenAI. Verifica la configuración de la API key.",
                    ) from exc
                if "rate limit" in error_msg.lower() or "quota" in error_msg.lower():
                    raise ChatCompletionFailed(
                        detail="Límite de tasa excedido. Por favor, intenta de nuevo en unos momentos.",
                    ) from exc
                if "model" in error_msg.lower():
                    raise ChatCompletionFailed(
                        detail=f"Error con el modelo de OpenAI: {error_msg}",
                    ) from exc
                raise ChatCompletionFailed(
                    detail=f"No fue posible generar la respuesta en este momento: {error_msg}",
                ) from exc

            metadata: dict = {"usage": usage}
            if retrieval.diagnostics:
                metadata["rag_diagnostics"] = retrieval.diagnostics
            if retrieval.analysis is not None:
                metadata["query_analysis"] = retrieval.analysis.to_dict()
            if response_mode:
                metadata["response_mode"] = response_mode
            if retrieval.recommended_documents:
                metadata["recommended_documents"] = retrieval.recommended_documents

            assistant_message = ChatMessage.objects.create(
                session=session,
                role=MessageRole.ASSISTANT,
                content=answer_text,
                chunk_ids=retrieval.chunk_ids,
                metadata=metadata,
            )
            touch_chat_session_activity(session.pk)

        response_payload = {
            "user_message": ChatMessageSerializer(user_message).data,
            "assistant_message": ChatMessageSerializer(assistant_message).data,
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)


def _build_chat_messages(
    session: ChatSession,
    content: str,
    user,
    *,
    response_mode: str | None = None,
    max_history: int = MAX_HISTORY_MESSAGES,
):
    """
    Shared helper used by the streaming endpoint.
    Returns (openai_messages, retrieval_result).
    """
    retrieval = _run_retrieval(session, content, user, response_mode=response_mode)
    messages = _compose_messages(
        session,
        content,
        retrieval,
        response_mode=response_mode,
        max_history=max_history,
    )
    return messages, retrieval


def _sync_session_documents_for_request(
    session: ChatSession, document_slugs: list[str] | None
):
    """
    Optionally update session scope before retrieval so each message can use
    the latest selected sources from the workspace UI.
    """
    if document_slugs is None:
        return
    docs = Document.objects.filter(slug__in=document_slugs)
    session.allowed_documents.set(docs)


class ChatMessageStreamView(APIView):
    """
    POST /chat/messages/stream/

    SSE endpoint — streams the assistant reply token-by-token.

    Event types sent:
      • {"type": "user_message", "message": {...}}   — the persisted user ChatMessage
      • {"type": "chunk",        "content": "..."}   — incremental text fragment
      • {"type": "done",         "message": {...}}   — the persisted assistant ChatMessage
      • {"type": "error",        "detail":  "..."}   — on failure (user message is rolled back)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChatMessageCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.validated_data["session"]
        content = serializer.validated_data["content"]
        document_slugs = serializer.validated_data.get("document_slugs")
        response_mode = serializer.validated_data.get("response_mode")

        _sync_session_documents_for_request(session, document_slugs)
        messages, retrieval = _build_chat_messages(
            session,
            content,
            request.user,
            response_mode=response_mode,
        )

        user_message = ChatMessage.objects.create(
            session=session,
            role=MessageRole.USER,
            content=content,
        )

        def _event(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def stream():
            yield _event(
                {
                    "type": "user_message",
                    "message": ChatMessageSerializer(user_message).data,
                }
            )

            collected: list[str] = []
            try:
                for text_chunk in client_openia.generate_chat_completion_stream(
                    messages,
                    model=session.model,
                    temperature=session.temperature,
                ):
                    collected.append(text_chunk)
                    yield _event({"type": "chunk", "content": text_chunk})

                answer_text = "".join(collected)
                metadata: dict = {}
                if retrieval.diagnostics:
                    metadata["rag_diagnostics"] = retrieval.diagnostics
                if retrieval.analysis is not None:
                    metadata["query_analysis"] = retrieval.analysis.to_dict()
                if response_mode:
                    metadata["response_mode"] = response_mode
                if retrieval.recommended_documents:
                    metadata["recommended_documents"] = retrieval.recommended_documents
                assistant_message = ChatMessage.objects.create(
                    session=session,
                    role=MessageRole.ASSISTANT,
                    content=answer_text,
                    chunk_ids=retrieval.chunk_ids,
                    metadata=metadata,
                )
                touch_chat_session_activity(session.pk)
                yield _event(
                    {
                        "type": "done",
                        "message": ChatMessageSerializer(assistant_message).data,
                    }
                )

            except Exception as exc:
                logger.exception(
                    "Streaming chat completion failed (session=%s): %s", session.id, exc
                )
                user_message.delete()
                yield _event({"type": "error", "detail": str(exc)})

        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
