import json
import logging
import os
import uuid

from apps.document.models import SmartChunk
from apps.document.utils.client_openia import embed_text, generate_chat_completion
from apps.document.utils.client_tiktoken import encode_text, decode_text, token_count

logger = logging.getLogger(__name__)

SMARTCHUNK_ENRICH_ENABLED = os.environ.get("SMARTCHUNK_ENRICH_ENABLED", "false").lower() == "true"


def chunk_text(text: str, max_tokens: int = 500, overlap: int = 50) -> list[str]:
    tokens = encode_text(text)
    chunks = []
    i = 0

    while i < len(tokens):
        chunk_tokens = tokens[i:i+max_tokens]
        chunk_text = decode_text(chunk_tokens)
        chunks.append(chunk_text)
        i += max_tokens - overlap

    return chunks

# def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
#     """
#     Splits the input text into smaller chunks of specified size.
#     If a paragraph is larger than the chunk size, it will be split further."""
#     paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
#     result = []
#     for p in paragraphs:
#         if len(p) <= chunk_size:
#             result.append(p)
#         else:
#             result.extend([p[i:i + chunk_size] for i in range(0, len(p), chunk_size)])
    
#     return result

def _enrich_chunks_with_metadata(chunks: list[SmartChunk]) -> None:
    """
    Optionally enrich SmartChunk instances with title, summary and keywords
    using the LLM before they are persisted.
    """
    if not SMARTCHUNK_ENRICH_ENABLED:
        return

    if not chunks:
        return

    for chunk in chunks:
        try:
            # Prompt the model to return a small JSON payload with metadata
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Eres un asistente que genera metadatos para secciones de documentos. "
                        "Devuelve SIEMPRE una respuesta en formato JSON válido con las claves: "
                        '"title" (string corta), "summary" (string) y "keywords" (lista de strings en minúsculas).'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Genera metadatos para el siguiente texto de un documento:\n\n"
                        f"{chunk.content}"
                    ),
                },
            ]

            response_text, _usage = generate_chat_completion(
                messages,
                temperature=0.1,
            )

            meta = json.loads(response_text)
            title = meta.get("title") or ""
            summary = meta.get("summary") or ""
            keywords = meta.get("keywords") or []

            # Normalizar tipos
            if not isinstance(title, str):
                title = str(title)
            if not isinstance(summary, str):
                summary = str(summary)
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
            keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]

            chunk.title = title[:255] if title else None
            chunk.summary = summary
            chunk.keywords = keywords
        except Exception as exc:  # pragma: no cover - network failure / parsing
            # Fallback silencioso: mantenemos los valores por defecto del modelo
            logger.warning(
                "No se pudieron enriquecer metadatos de SmartChunk id=%s: %s",
                getattr(chunk, "id", None),
                exc,
            )


def chunk_text_and_embed(text: str, document_id: uuid.UUID) -> list[SmartChunk]:
    raw_chunks = chunk_text(text)
    result = [
        SmartChunk(
            document_id=document_id,
            chunk_index=i,
            content=chunk,
            token_count=token_count(chunk),
            embedding=embed_text(chunk),
        )
        for i, chunk in enumerate(raw_chunks)
    ]
    # Opcionalmente enriquecer con metadatos generados por el modelo
    _enrich_chunks_with_metadata(result)
    return result

def chunk_text_and_embed_origin(text: str, document_id: uuid.UUID) -> list[SmartChunk]:
    raw_chunks = chunk_text(text)
    result = [
        SmartChunk(
            document_id=document_id,
            chunk_index=i,
            content=chunk,
            token_count=len(chunk.split()),
            embedding=embed_text(chunk),
        )
        for i, chunk in enumerate(raw_chunks)
    ]
    return result
