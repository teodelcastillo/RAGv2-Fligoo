import logging

from apps.document.models import SmartChunk
from apps.document.utils.client_openia import embed_text, generate_chunk_context
from apps.document.utils.client_tiktoken import encode_text, decode_text, token_count

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_tokens: int = 500, overlap: int = 100)-> list[str]:
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

def chunk_text_and_embed(
    text: str,
    document_id: int,
    *,
    document_name: str = "",
    content_summary: str | None = None,
) -> list[SmartChunk]:
    """
    Parte el texto en chunks con embeddings. Si ``content_summary`` está presente,
    inserta un primer fragmento con título + resumen para que la búsqueda vectorial
    refleje el propósito del documento aunque el PDF empiece con portada o texto poco útil.
    """
    result: list[SmartChunk] = []
    idx = 0
    title = (document_name or "").strip()
    summary = (content_summary or "").strip()
    if summary:
        parts: list[str] = []
        if title:
            parts.append(f"Documento: {title}")
        parts.append(f"Resumen general: {summary}")
        brief = "\n".join(parts)
        result.append(
            SmartChunk(
                document_id=document_id,
                chunk_index=idx,
                content=brief,
                token_count=token_count(brief),
                embedding=embed_text(brief),
            )
        )
        idx += 1

    raw_chunks = chunk_text(text)
    for chunk in raw_chunks:
        ctx = ""
        try:
            ctx = generate_chunk_context(
                chunk_content=chunk,
                doc_name=document_name,
                doc_summary=content_summary or "",
                chunk_index=idx,
            )
        except Exception as exc:
            logger.warning("Chunk context generation failed for chunk %d: %s", idx, exc)

        embed_input = f"{ctx}\n\n{chunk}" if ctx else chunk
        result.append(
            SmartChunk(
                document_id=document_id,
                chunk_index=idx,
                content=chunk,
                context_summary=ctx,
                token_count=token_count(chunk),
                embedding=embed_text(embed_input),
            )
        )
        idx += 1
    return result

def chunk_text_and_embed_origin(text: str, document_id: int) -> list[SmartChunk]:
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
