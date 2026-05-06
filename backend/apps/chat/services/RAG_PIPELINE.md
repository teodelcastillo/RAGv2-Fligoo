# RAG Pipeline — Architecture & Roadmap

Este documento describe la arquitectura RAG de Ecofilia tras la refactorización
de mayo 2026 y deja una hoja de ruta para llevarla a un nivel profesional/SOTA.

## 1. Pipeline actual (alto nivel)

```
   ┌────────────────────┐
   │  user message      │
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐
   │ query_analysis.py  │  classify (factual/numeric/comparative/panorama)
   │                    │  + heurística de sub-queries
   │                    │  + (opcional) expansión LLM
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐
   │ retrieval.py       │  vector via fetch_relevant_chunks (pgvector)
   │  + lexical search  │  lexical via TrigramSimilarity sobre content_norm
   │  + RRF fusion      │  Reciprocal Rank Fusion (k=60 por defecto)
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐
   │ reranker.py (opt)  │  LLM listwise rerank (RAG_RERANKER_ENABLED=1)
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐
   │ context_builder.py │  per-doc cap + (opcional) MMR diversity
   │  build_context     │  citation tags [#N] inyectadas en el prompt
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐
   │ chat completion    │  prompt: system + ctx + history + user
   │  (OpenAI)          │  modelo: session.model (default gpt-4o-mini)
   └────────────────────┘
```

Punto de entrada principal: `apps.chat.services.rag.retrieve_for_chat(...)`.

Devuelve un `RetrievalResult` con `chunks`, `context_block`, `analysis` y
`diagnostics` (latencia, candidatos por etapa, doc únicos, etc.). Esos
`diagnostics` se persisten en `ChatMessage.metadata.rag_diagnostics` y son la
base para observabilidad y evaluación.

## 2. Módulos

| Módulo | Responsabilidad |
|--------|-----------------|
| `query_analysis.py` | Clasifica la pregunta y genera sub-queries (heurística + LLM opcional). |
| `retrieval.py` | Búsqueda léxica con `TrigramSimilarity`, fusión RRF y per-doc cap. |
| `reranker.py` | Reranker listwise con LLM (env-gated) y fallback identidad. |
| `context_builder.py` | Construcción de contexto con citas `[#N]`, MMR opcional. |
| `rag.py` | Orquestador `retrieve_for_chat` + retriever legacy `fetch_relevant_chunks`. |
| `rag_evaluation.py` | Eval offline con métricas: coverage, keyword recall, fuentes, latencia. |
| `management/commands/rag_eval.py` | Wrapper Django para correr la eval desde shell/CI. |

## 3. Variables de entorno

Todas opcionales; los defaults son seguros para producción.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `CHAT_CONTEXT_CHUNKS` | `8` | Chunks finales en el contexto cuando no se especifica. |
| `RAG_RERANK_POOL` | `20` | Tamaño del pool tras la fusión, antes del rerank. |
| `RAG_VECTOR_POOL_MULTIPLIER` | `2.5` | Pool vectorial = `top_n * mult`. |
| `RAG_LEXICAL_POOL_MULTIPLIER` | `2.0` | Pool léxico = `top_n * mult`. |
| `RAG_RRF_K` | `60` | Constante k de RRF. |
| `RAG_LEXICAL_TOP_N` | `20` | Top-N por defecto del léxico. |
| `RAG_LEXICAL_MIN_SIMILARITY` | `0.05` | Umbral de TrigramSimilarity. |
| `RAG_RERANKER_ENABLED` | `0` | Activa el reranker LLM (más calidad, más costo). |
| `RAG_RERANKER_MODEL` | `gpt-4o-mini` | Modelo del reranker. |
| `RAG_QUERY_EXPANSION_ENABLED` | `0` | Activa la expansión LLM de sub-queries. |
| `RAG_QUERY_EXPANSION_MODEL` | `gpt-4o-mini` | Modelo de la expansión. |
| `RAG_MMR_ENABLED` | `0` | Activa diversidad MMR sobre el final. |

## 4. Cómo correr la evaluación

```bash
# 1) Crear un dataset mínimo
cat > /tmp/cases.json <<'EOF'
[
  {
    "question": "Dame un panorama de los reportes de sostenibilidad",
    "expected_document_slugs": ["reporte-2023", "reporte-2024"],
    "expected_keywords": ["emisiones", "gobernanza", "alcance 1"]
  },
  {
    "question": "¿Cuál es el % de reducción de emisiones reportado?",
    "expected_document_slugs": ["reporte-2024"],
    "expected_keywords": ["reducción", "emisiones"]
  }
]
EOF

# 2) Ejecutar
python manage.py rag_eval \
  --user-email owner@example.com \
  --cases /tmp/cases.json \
  --top-n 12
```

Salida (ejemplo):

```
RAG eval — 2 cases
  coverage@k        : 0.875
  keyword_recall@k  : 0.833
  avg unique sources: 3.5
  avg chunks        : 9.0
  avg latency (s)   : 1.42
- 'Dame un panorama de los reportes de sostenibilidad'  cov=1.00  kw=0.67  sources=4  chunks=10  lat=1.61s
- '¿Cuál es el % de reducción de emisiones reportado?'  cov=0.75  kw=1.00  sources=3  chunks=8  lat=1.23s
```

## 5. Observabilidad

Cada respuesta del asistente persiste:

- `metadata.usage` — tokens (input/output/total).
- `metadata.rag_diagnostics` — `vector_candidates`, `lexical_candidates`,
  `fused_candidates`, `final_chunks`, `unique_documents`, `query_type`,
  `sub_queries`, `reranked`, `mmr_applied`, `elapsed_seconds`.
- `metadata.query_analysis` — clasificación + keywords + numeric tokens.
- `chunk_ids` — índice de fuentes citables (resoluble vía API).

Esto habilita dashboards y alertas (ej: alertar cuando
`final_chunks < 4` y `query_type == panorama`).

## 6. Roadmap profesional

**Fase 1 — calidad inmediata (hecho)**
- [x] Clasificación + sub-queries heurísticas.
- [x] Hybrid retrieval (vector + trigram) con fusión RRF.
- [x] Reranker LLM (env-gated).
- [x] Context builder con citas `[#N]` y per-doc cap.
- [x] Diagnostics persistidos por mensaje.
- [x] Eval harness CLI.

**Fase 2 — calidad sostenida (1-2 semanas)**
- [ ] Dataset de eval real (≥30 casos por dominio: regulación, finanzas, KPIs).
- [ ] Reranker open-source local (BAAI/bge-reranker-v2-m3) detrás del flag para
  reducir costo del rerank LLM en producción.
- [ ] Chunking por tipo de documento: PDF (layout-aware), tablas
  (sliding window con header), regulación (por artículo), texto libre
  (semántico). El chunker actual es token-based fijo (500/50).
- [ ] Mejor signaling al frontend: incluir `query_analysis` en la respuesta y
  pintar "fuentes consultadas vs citadas".

**Fase 3 — RAG profesional (1 mes)**
- [ ] **Reranker remoto especializado** (Cohere Rerank o Voyage rerank) con
  benchmarking A/B contra LLM rerank.
- [ ] **Multi-vector / late interaction** (ej. ColBERT-lite) para preguntas
  largas y comparativas.
- [ ] **Query routing**: decidir entre "responder sin RAG", "RAG global", "RAG
  por proyecto" o "agente multi-step" según `QueryAnalysis`.
- [ ] **Self-correction**: post-check del LLM que verifica que cada afirmación
  citada `[#N]` esté soportada por el chunk N (aborta y reintenta si no).
- [ ] **Caching**: cache LRU de query → embedding y query → top-K results,
  invalidando por `document_updated_at`.

**Fase 4 — escala y producto (continuo)**
- [ ] Replicar `rag_diagnostics` a un sink de observabilidad (CloudWatch /
  Datadog) y armar SLOs (p95 < 2s, coverage media > 0.7).
- [ ] Eval continuo en CI: PRs que bajan métricas se marcan ⚠.
- [ ] Feedback loop: thumbs up/down en la UI alimentan un dataset nuevo de eval
  + ejemplos para fine-tuning del reranker.
- [ ] Multi-tenant tuning: por cliente, ajustar `k_per_doc`, `total_limit`,
  `RAG_RERANKER_ENABLED`, modelo, etc., desde un panel de admin.

## 7. Reglas operativas

1. **No bloquear el chat por fallas de RAG.** Toda excepción del pipeline cae
   en `_run_retrieval` con `try/except` y se devuelve un `RetrievalResult`
   vacío. El LLM responde con base knowledge y un disclaimer.
2. **Citas siempre que haya contexto.** El system prompt incluye
   `build_citation_prompt()` y el contexto numera cada fragmento con `[#N]`.
3. **Defaults conservadores.** Reranker, MMR y expansión LLM están
   deshabilitados por defecto. Activar progresivamente con métricas en mano.
4. **`fetch_relevant_chunks` sigue siendo público** para retro-compatibilidad
   con tests y callers existentes; nuevas funcionalidades pasan por
   `retrieve_for_chat`.
