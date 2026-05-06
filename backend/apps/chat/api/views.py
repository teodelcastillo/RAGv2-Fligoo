from __future__ import annotations

import json
import logging
import os

from django.db import transaction
from django.db.models import Count
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
)
from apps.chat.models import ChatMessage, ChatSession, MessageRole
from apps.chat.services.context_builder import build_citation_prompt
from apps.chat.services.query_analysis import COVERAGE_MODE_ALL, classify_query
from apps.chat.services.rag import RetrievalResult, retrieve_for_chat
from apps.document.utils import client_openia

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = int(os.environ.get("CHAT_HISTORY_MESSAGES", "10"))


def _chat_retrieval_params(session: ChatSession, content: str) -> dict:
    """
    Heuristic sizing for the RAG retrieval pool given the session scope and
    the current message. Wider pools for broader questions and bigger libraries.
    """
    doc_count = session.allowed_documents.count()
    analysis = classify_query(content)
    broad_question = len((content or "").split()) >= 18
    if analysis.coverage_mode == COVERAGE_MODE_ALL:
        total_limit = doc_count
        max_chunks_per_doc = 1
    else:
        total_limit = min(18, max(8, doc_count * 2))
        max_chunks_per_doc = 2
    if not broad_question and analysis.coverage_mode != COVERAGE_MODE_ALL:
        total_limit = min(total_limit, 12)
    return {
        "top_n": total_limit,
        "total_limit": total_limit,
        "k_per_doc": 2,
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


def _run_retrieval(session: ChatSession, content: str, user) -> RetrievalResult:
    """
    Defensive wrapper around ``retrieve_for_chat``. Failures (embeddings,
    pgvector, OpenAI keys) must not bubble up as 500s — return an empty
    result so the chat still answers using base knowledge.
    """
    allowed_docs = session.allowed_documents.all()
    if not allowed_docs.exists():
        return RetrievalResult()
    try:
        return retrieve_for_chat(
            user=user,
            query_text=content,
            allowed_documents=allowed_docs,
            **_chat_retrieval_params(session, content),
        )
    except Exception as exc:
        logger.exception("Chat RAG pipeline failed (session=%s): %s", session.id, exc)
        return RetrievalResult()


def _compose_messages(
    session: ChatSession,
    content: str,
    retrieval: RetrievalResult,
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
        base_messages.append(
            {
                "role": str(MessageRole.SYSTEM),
                "content": (
                    "El siguiente contexto proviene de los documentos del usuario. "
                    "Prioriza este contexto para responder. "
                    "Si la información del contexto es suficiente, basate principalmente en ella. "
                    "Si el contexto no contiene información relevante o es insuficiente, "
                    "puedes complementar con tu conocimiento general, pero indica claramente "
                    "qué parte proviene del documento y qué parte de tu conocimiento general. "
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
                base = base.annotate(_ecofilia_msg_count=Count("messages")).filter(
                    _ecofilia_msg_count__gt=0
                )
        return base

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
        qs = (
            ChatMessage.objects.select_related("session", "session__owner")
            .prefetch_related("session__allowed_documents")
            .order_by("created_at")
        )
        if self.request.user.is_staff:
            return qs
        return qs.filter(session__owner=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = ChatMessageCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.validated_data["session"]
        content = serializer.validated_data["content"]

        retrieval = _run_retrieval(session, content, request.user)
        messages = _compose_messages(session, content, retrieval)

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

            assistant_message = ChatMessage.objects.create(
                session=session,
                role=MessageRole.ASSISTANT,
                content=answer_text,
                chunk_ids=retrieval.chunk_ids,
                metadata=metadata,
            )

        response_payload = {
            "user_message": ChatMessageSerializer(user_message).data,
            "assistant_message": ChatMessageSerializer(assistant_message).data,
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)


def _build_chat_messages(session: ChatSession, content: str, user, max_history: int = MAX_HISTORY_MESSAGES):
    """
    Shared helper used by the streaming endpoint.
    Returns (openai_messages, retrieval_result).
    """
    retrieval = _run_retrieval(session, content, user)
    messages = _compose_messages(session, content, retrieval, max_history=max_history)
    return messages, retrieval


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

        messages, retrieval = _build_chat_messages(session, content, request.user)

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
                assistant_message = ChatMessage.objects.create(
                    session=session,
                    role=MessageRole.ASSISTANT,
                    content=answer_text,
                    chunk_ids=retrieval.chunk_ids,
                    metadata=metadata,
                )
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
