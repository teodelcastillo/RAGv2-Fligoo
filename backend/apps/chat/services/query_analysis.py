"""
Query analysis utilities for the RAG pipeline.

Goals:
- Classify the user's question (factual / comparative / panorama / numeric).
- Optionally decompose broad questions into sub-questions to widen retrieval.
- Extract simple entities/keywords useful for lexical retrieval.

Heuristics first (cheap, deterministic) and optional LLM expansion behind an env
flag (RAG_QUERY_EXPANSION_ENABLED) to avoid extra cost during dev/tests.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


QUERY_TYPE_FACTUAL = "factual"
QUERY_TYPE_NUMERIC = "numeric"
QUERY_TYPE_COMPARATIVE = "comparative"
QUERY_TYPE_PANORAMA = "panorama"
QUERY_TYPE_EXTRACTION = QUERY_TYPE_NUMERIC

COVERAGE_MODE_FOCUSED = "focused"
COVERAGE_MODE_BALANCED = "balanced"
COVERAGE_MODE_ALL = "all"

RESPONSE_MODE_PUNTUAL = "puntual"
RESPONSE_MODE_PANORAMA = "panorama"
RESPONSE_MODE_COMPARACION = "comparacion"
RESPONSE_MODE_EXTRACCION = "extraccion"
RESPONSE_MODE_TABLA = "tabla"

_PANORAMA_PATTERNS = (
    r"\b(resumen|panorama|vision|visión|overview|síntesis|sintesis)\b",
    r"\b(general|global|integral|completo|completa)\b",
    r"\b(todo|toda|todos|todas|cada (uno|una))\b",
    r"\b(base documental|documentacion|documentación|biblioteca|repositorio|repository)\b",
    r"\b(rasgos generales|de qu[eé] trata|en t[eé]rminos generales)\b",
    r"\b(overall|high[- ]level|across|across all)\b",
)

_ALL_COVERAGE_PATTERNS = (
    r"\b(cada documento|cada uno|cada una|uno por documento|una por documento)\b",
    r"\b(todos los documentos|todas las fuentes|documentos seleccionados)\b",
    r"\b(repositorio|repository|base documental|biblioteca|documentaci[oó]n)\b",
    r"\b(rasgos generales|panorama general|visi[oó]n general|overview|overall)\b",
)

_COMPARATIVE_PATTERNS = (
    r"\b(compar[aá]r?|compara|comparativo|comparativa|comparativos|comparativas)\b",
    r"\b(diferencias?|similitudes?|versus|vs\.?|frente a)\b",
    r"\b(entre [^.,]+? y )",
    r"\b(cu[áa]l (es )?(mejor|peor)|ranking)\b",
)

_NUMERIC_PATTERNS = (
    r"\b(cu[áa]nt[oa]s?|how many|how much|porcentaje|%|monto|valor|t[oó]nelad[ao]s?|kg|mw|gw|kwh)\b",
    r"\b(emisiones|consumo|huella|capex|opex|ebitda|ingresos?|revenue|margen|roe|roi)\b",
)


@dataclass
class QueryAnalysis:
    """Structured representation of the user's question for retrieval."""

    raw_text: str
    normalized: str
    query_type: str = QUERY_TYPE_FACTUAL
    is_general: bool = False
    coverage_mode: str = COVERAGE_MODE_FOCUSED
    keywords: List[str] = field(default_factory=list)
    numeric_tokens: List[str] = field(default_factory=list)
    sub_queries: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query_type": self.query_type,
            "is_general": self.is_general,
            "coverage_mode": self.coverage_mode,
            "keywords": self.keywords,
            "numeric_tokens": self.numeric_tokens,
            "sub_queries": self.sub_queries,
        }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _extract_keywords(text: str, max_terms: int = 12) -> List[str]:
    """Cheap keyword extraction: words >= 4 chars, drop trivial stopwords."""
    if not text:
        return []
    stop = {
        # ES
        "para", "como", "cual", "cuál", "cuáles", "cuales", "donde", "dónde",
        "cuando", "cuándo", "porque", "según", "segun", "entre", "sobre", "todo",
        "todos", "todas", "toda", "este", "esta", "esto", "ese", "esa", "eso",
        "tener", "tiene", "hacer", "decir", "puedes", "puede", "pueden", "favor",
        "informacion", "información", "lista", "listame", "listar", "necesito",
        "quisiera",
        # EN
        "what", "which", "where", "when", "with", "from", "into", "about",
        "please", "could", "would", "should", "have", "their", "there", "these",
        "those", "list", "show",
    }
    tokens = [t for t in re.findall(r"[a-záéíóúñü0-9]+", text.lower()) if len(t) >= 4]
    seen: set[str] = set()
    out: List[str] = []
    for t in tokens:
        if t in stop or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_terms:
            break
    return out


def _extract_numeric_tokens(text: str) -> List[str]:
    return re.findall(r"\d+(?:[\.,]\d+)?", text or "")


def classify_query(text: str) -> QueryAnalysis:
    """
    Classify a user query into a coarse RAG-relevant type.
    Always returns a QueryAnalysis; never raises on bad input.
    """
    norm = _normalize(text)
    analysis = QueryAnalysis(raw_text=text or "", normalized=norm)
    if not norm:
        return analysis

    analysis.keywords = _extract_keywords(norm)
    analysis.numeric_tokens = _extract_numeric_tokens(norm)

    is_panorama = any(re.search(p, norm) for p in _PANORAMA_PATTERNS)
    all_coverage_hits = sum(1 for p in _ALL_COVERAGE_PATTERNS if re.search(p, norm))
    is_comparative = any(re.search(p, norm) for p in _COMPARATIVE_PATTERNS)
    is_numeric = any(re.search(p, norm) for p in _NUMERIC_PATTERNS) or bool(
        analysis.numeric_tokens
    )

    long_question = len(norm.split()) >= 18

    if is_comparative:
        analysis.query_type = QUERY_TYPE_COMPARATIVE
    elif is_panorama or long_question:
        analysis.query_type = QUERY_TYPE_PANORAMA
    elif is_numeric:
        analysis.query_type = QUERY_TYPE_NUMERIC
    else:
        analysis.query_type = QUERY_TYPE_FACTUAL

    analysis.is_general = analysis.query_type in {
        QUERY_TYPE_PANORAMA,
        QUERY_TYPE_COMPARATIVE,
    } or long_question

    if all_coverage_hits >= 2:
        analysis.coverage_mode = COVERAGE_MODE_ALL
    elif analysis.query_type in {QUERY_TYPE_PANORAMA, QUERY_TYPE_COMPARATIVE}:
        analysis.coverage_mode = COVERAGE_MODE_BALANCED
    else:
        analysis.coverage_mode = COVERAGE_MODE_FOCUSED

    analysis.sub_queries = _heuristic_sub_queries(analysis)
    return analysis


def apply_response_mode_override(
    analysis: QueryAnalysis,
    response_mode: str | None,
) -> QueryAnalysis:
    """
    Deterministic override from explicit frontend selector.
    If provided, this mode takes precedence over heuristic classification.
    """
    mode = (response_mode or "").strip().lower()
    if not mode:
        return analysis

    if mode == RESPONSE_MODE_PUNTUAL:
        analysis.query_type = QUERY_TYPE_FACTUAL
        analysis.coverage_mode = COVERAGE_MODE_FOCUSED
        analysis.is_general = False
        analysis.sub_queries = []
        return analysis

    if mode == RESPONSE_MODE_PANORAMA:
        analysis.query_type = QUERY_TYPE_PANORAMA
        analysis.coverage_mode = COVERAGE_MODE_ALL
        analysis.is_general = True
        analysis.sub_queries = _heuristic_sub_queries(analysis)
        return analysis

    if mode == RESPONSE_MODE_COMPARACION:
        analysis.query_type = QUERY_TYPE_COMPARATIVE
        analysis.coverage_mode = COVERAGE_MODE_BALANCED
        analysis.is_general = True
        analysis.sub_queries = _heuristic_sub_queries(analysis)
        return analysis

    if mode == RESPONSE_MODE_EXTRACCION:
        analysis.query_type = QUERY_TYPE_NUMERIC
        analysis.coverage_mode = COVERAGE_MODE_FOCUSED
        analysis.is_general = False
        analysis.sub_queries = []
        return analysis

    if mode == RESPONSE_MODE_TABLA:
        analysis.query_type = QUERY_TYPE_NUMERIC
        analysis.coverage_mode = COVERAGE_MODE_FOCUSED
        analysis.is_general = False
        analysis.sub_queries = []
        return analysis

    return analysis


def _heuristic_sub_queries(analysis: QueryAnalysis) -> List[str]:
    """Cheap, language-agnostic decomposition.

    For panorama/comparative questions we synthesize a couple of focused
    sub-queries from extracted keywords so the retriever has multiple anchors.
    """
    if analysis.query_type not in {QUERY_TYPE_PANORAMA, QUERY_TYPE_COMPARATIVE}:
        return []
    if not analysis.keywords:
        return []
    # Group keywords in pairs to form mini-queries.
    kws = analysis.keywords[:6]
    pairs: list[str] = []
    for i in range(0, len(kws), 2):
        pair = " ".join(kws[i : i + 2])
        if pair:
            pairs.append(pair)
    return pairs[:3]


def expand_query_with_llm(
    analysis: QueryAnalysis,
    *,
    max_subqueries: int = 3,
    model: str | None = None,
) -> List[str]:
    """
    Use an LLM to produce focused sub-queries for broad questions.
    Disabled by default; opt-in via RAG_QUERY_EXPANSION_ENABLED=1.
    """
    enabled = os.environ.get("RAG_QUERY_EXPANSION_ENABLED", "0").lower() in (
        "1", "true", "yes", "on",
    )
    if not enabled or not analysis.is_general:
        return []
    try:
        from apps.document.utils.client_openia import generate_chat_completion

        prompt = (
            "Eres un asistente que genera sub-preguntas para mejorar un sistema RAG. "
            "A partir de la pregunta del usuario, devuelve un JSON array con "
            f"hasta {max_subqueries} sub-preguntas concretas, en el mismo idioma "
            "y orientadas a recuperar evidencias específicas en documentos. "
            "Si la pregunta ya es específica, devuelve []."
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": analysis.raw_text},
        ]
        text, _ = generate_chat_completion(
            messages,
            model=model or os.environ.get("RAG_QUERY_EXPANSION_MODEL", "gpt-4o-mini"),
            temperature=0.1,
            max_tokens=200,
            timeout=15,
        )
        text = text.strip()
        # Try direct JSON parse; fallback to extracting bracketed array.
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            text = match.group(0)
        items = json.loads(text)
        if isinstance(items, list):
            return [str(it).strip() for it in items if str(it).strip()][:max_subqueries]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Query expansion failed, falling back to heuristics: %s", exc)
    return []


def contextualize_query(
    current_query: str,
    history: list[dict],
    *,
    model: str | None = None,
) -> str:
    """
    Rewrite a follow-up question as a standalone query using conversation
    history. If the question is already self-contained, returns it unchanged.

    ``history`` is a list of ``{"role": "user"|"assistant", "content": ...}``
    messages, most recent last. Only the last few turns are used.
    """
    text = (current_query or "").strip()
    if not text:
        return text

    if not history:
        return text

    recent = history[-6:]

    history_block = "\n".join(
        f"{'Usuario' if m['role'] == 'user' else 'Asistente'}: {(m.get('content') or '')[:300]}"
        for m in recent
    )

    try:
        from apps.document.utils.client_openia import generate_chat_completion

        messages = [
            {
                "role": "system",
                "content": (
                    "Tu tarea es reformular la última pregunta del usuario para que sea "
                    "una consulta de búsqueda autocontenida, incorporando contexto del "
                    "historial de conversación cuando sea necesario. "
                    "Si la pregunta ya es autocontenida, devuélvela tal cual. "
                    "Responde ÚNICAMENTE con la consulta reformulada, sin explicaciones."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Historial de conversación:\n{history_block}\n\n"
                    f"Última pregunta del usuario: {text}\n\n"
                    "Consulta reformulada:"
                ),
            },
        ]
        result, _ = generate_chat_completion(
            messages,
            model=model or os.environ.get("RAG_QUERY_REWRITE_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=200,
            timeout=10,
        )
        rewritten = (result or "").strip()
        if rewritten:
            logger.debug("Query rewrite: %r -> %r", text, rewritten)
            return rewritten
    except Exception as exc:
        logger.warning("Query contextualization failed, using original: %s", exc)

    return text


def build_query_set(analysis: QueryAnalysis) -> List[str]:
    """
    Produce the final list of search queries to execute.
    Always includes the original query first.
    """
    queries: List[str] = []
    if analysis.raw_text:
        queries.append(analysis.raw_text)

    llm_subs = expand_query_with_llm(analysis)
    queries.extend(llm_subs)
    if not llm_subs:
        queries.extend(analysis.sub_queries)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: List[str] = []
    for q in queries:
        key = _normalize(q)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    return deduped or ([analysis.raw_text] if analysis.raw_text else [])
