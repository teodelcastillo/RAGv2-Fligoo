# RAG Eval Harness — Fase 0 ("la vara")

Herramienta de **QA/dev** (no es el app `evaluation`, que es el producto de scoring ESG).
Sirve para medir, con números, si un cambio en el RAG mejora **calidad** y
**cobertura** antes de tocar nada más.

Corre el **path real de producción** (recuperación + generación), no una
reimplementación, y puntúa cada caso contra una verdad conocida.

## Cómo correr

```bash
# Eval completa (recuperación + generación + LLM-juez)
python manage.py rag_eval_quality --user-email owner@example.com --cases evals/cases.json

# Registrar un baseline
python manage.py rag_eval_quality --user-email me@x.com --cases evals/cases.json \
    --out evals/baseline.json

# Comparar una corrida posterior contra el baseline
python manage.py rag_eval_quality --user-email me@x.com --cases evals/cases.json \
    --baseline evals/baseline.json

# Solo recuperación (sin LLM, 100% offline) — útil para iterar barato sobre el retrieval
python manage.py rag_eval_quality --user-email me@x.com --cases evals/cases.json \
    --skip-generation
```

Requisitos para una corrida completa: DB con los documentos reales cargados y
procesados (embeddings), y `OPENAI_API_KEY` (para generación + juez). Sin API
key, usá `--skip-generation` y obtenés solo las métricas de recuperación.

## Las tres métricas que importan

| Métrica | Qué responde | Cómo se calcula |
|---|---|---|
| **retrieval_recall** (docs / pages) | ¿Se *recuperó* la evidencia que existe? | Determinístico: docs/páginas esperadas presentes en los chunks recuperados |
| **answer_recall** | ¿La *respuesta final* incluyó el dato? | LLM-juez sobre `expected_facts` |
| **cited_any / citation_correctness / expected_evidence_cited** | ¿Demostró de dónde salió? | Mapeo determinístico de `[#N]` → chunk → documento/página esperada |
| **abstention_rate / fabrication_rate** (casos negativos) | ¿Dijo "no está" en vez de inventar? | LLM-juez |
| **faithfulness_rate** (casos positivos) | ¿Toda afirmación está respaldada por el contexto? | LLM-juez |

> **La brecha entre `retrieval_recall` y `answer_recall` localiza la falla:**
> si se recuperó pero no apareció en la respuesta → falla de generación;
> si no se recuperó → falla de retrieval. Esa es la distinción "no está" vs
> "no lo busqué" hecha número.

## Formato de un caso

Lista JSON. Cada objeto:

```json
{
  "id": "urbancode-altura-r1",
  "task_type": "numeric",
  "scope": "single_doc",
  "question": "¿Cuál es la altura máxima de edificación en zona R1?",
  "expected_document_slugs": ["codigo-urbano-xyz"],
  "expected_facts": ["12 metros", "4 niveles"],
  "expected_evidence": [{"document_slug": "codigo-urbano-xyz", "page": 14}],
  "answer_exists": true,
  "expected_keywords": ["altura", "zona"],
  "notes": "el dato vive en una tabla de zonificación"
}
```

| Campo | Obligatorio | Uso |
|---|---|---|
| `question` | sí | la consulta |
| `id` | recomendado | identificador estable (para diffs) |
| `task_type` | sí | `factual` \| `numeric` \| `extract_per_entity` \| `comparative` \| `panorama` |
| `scope` | informativo | `single_doc` \| `few_docs` \| `many_docs` \| `repository` |
| `expected_document_slugs` | para recall | docs donde vive la respuesta |
| `expected_facts` | para answer_recall | hechos/valores que la respuesta DEBE incluir |
| `expected_evidence` | para provenance | `[{document_slug, page}]` — ubicación exacta |
| `answer_exists` | sí | `false` ⇒ **caso negativo** (mide abstención) |
| `expected_keywords` | opcional | recall léxico sobre el texto recuperado (legacy) |
| `notes` | opcional | contexto para humanos |

## Cómo construir el dataset de oro

1. **Usá documentos reales** (anonimizados si hace falta) cargados en un
   workspace de prueba. Las métricas solo valen si reflejan tu realidad.
2. Reemplazá los `expected_document_slugs` de `cases.example.json` por los
   **slugs reales** de tus documentos (los ves en la URL/admin del documento).
3. **Cosechá consultas reales que fallaron** — como consultora ya las tenés;
   son el dataset más valioso.
4. Cubrí la taxonomía completa + casos negativos (`answer_exists: false`).
5. Empezá con ~20–40 casos y crecé. Mantené un subconjunto "smoke" chico para
   correr en cada cambio y el set completo para corridas nocturnas.

`cases.example.json` es una **plantilla** con slugs ficticios — copialo a
`cases.json` y completalo con tus documentos reales.

## Medir Fase 1 (recall del retrieval) contra el baseline

Los cambios de Fase 1 vienen **activados por default** y son reversibles por env
var. Para un A/B limpio, corré el harness dos veces sobre el mismo dataset:

```bash
# Baseline (comportamiento pre-Fase-1): umbral duro, budget fijo, sin expansión
RAG_RECALL_MODE=0 RAG_PARENT_EXPANSION=0 \
  python manage.py rag_eval_quality --user-email TU@email --cases evals/cases.json \
  --out evals/baseline.json

# Fase 1 (default ON) y diff contra el baseline
python manage.py rag_eval_quality --user-email TU@email --cases evals/cases.json \
  --baseline evals/baseline.json
```

Esperá ver subir `retrieval_recall` y `answer_recall` (sobre todo en los dos
cuellos de botella) sin que se desplome `faithfulness_rate`. Flags de Fase 1:

| Env var | Default | Qué controla |
|---|---|---|
| `RAG_RECALL_MODE` | `1` | El umbral de similitud deja de *descartar* evidencia; solo etiqueta confianza |
| `RAG_PER_DOC_FLOOR` | `1` | Chunks mínimos por documento en el budget adaptativo (tareas distribuidas) |
| `RAG_MAX_CONTEXT_CHUNKS` | `24` | Tope del budget adaptativo + expansión (evita reventar el contexto) |
| `RAG_PARENT_EXPANSION` | `1` | Small-to-big: expande cada chunk a sus vecinos (pasaje contiguo) |
| `RAG_PARENT_WINDOW` | `1` | Cuántos chunks vecinos a cada lado del ancla |

## Medir Fase 2 (migración de generación a Claude)

El ruteo es por **model-id**: cualquier id `claude-*` se despacha a Anthropic;
el resto sigue en OpenAI. Los embeddings NO se tocan (siguen en OpenAI), así que
no hay que re-embeber nada.

Dos formas de medir Claude vs OpenAI en el harness (necesitás `ANTHROPIC_API_KEY`):

```bash
# (a) Apuntar solo la generación del harness a Claude (juez sigue en OpenAI):
RAG_EVAL_ANSWER_MODEL=claude-sonnet-4-6 \
  python manage.py rag_eval_quality --user-email TU@email --cases evals/cases.json \
  --baseline evals/baseline.json

# (b) Flipear todo el motor a Claude por tiers (chat→Sonnet, router/rerank→Haiku):
LLM_PROVIDER=anthropic \
  python manage.py rag_eval_quality --user-email TU@email --cases evals/cases.json \
  --baseline evals/baseline.json
```

Flags de Fase 2:

| Env var | Default | Qué controla |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `anthropic` flipea los tiers a Claude (chat→Sonnet, máquina→Haiku, síntesis→Opus) |
| `LLM_MODEL_FAST` / `_BALANCED` / `_DEEP` | — | Override explícito del modelo por tier (gana sobre el provider) |
| `LLM_PROMPT_CACHING` | `1` | Cachea el prefijo de sistema/contexto (cache_control) en el path Anthropic |
| `LLM_THINKING` | `0` | Activa adaptive thinking en Claude para la respuesta |
| `LLM_MAX_TOKENS` | `4096` | `max_tokens` por defecto (Anthropic lo exige) |

> Embeddings siguen en `MODEL_EMBEDDING` (OpenAI). Tool-use de skills
> (`generate_with_tools`) y structured outputs / citas nativas quedan como
> follow-ups de Fase 2 — por ahora esos paths permanecen en OpenAI.

## Modelos (env vars)

- `RAG_EVAL_ANSWER_MODEL` — modelo de generación. Default: el de producción
  (`MODEL_COMPLETION`), para que el baseline refleje lo que ve el usuario hoy.
- `RAG_EVAL_JUDGE_MODEL` — modelo juez. Default: `MODEL_COMPLETION`. Se
  **recomienda un modelo más fuerte** y validar el juez contra un puñado de
  etiquetas humanas antes de confiar en él.
- `PROMPT_VERSION` (en `rag_eval_quality.py`) versiona los prompts de
  generación/juez: si los cambiás, subilo, para que un movimiento de métrica
  sea atribuible.
