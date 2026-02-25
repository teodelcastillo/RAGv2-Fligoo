# API de Tableros de Evaluación (Template-based)

Endpoints para los tableros analítico, comparativo e histórico.

## Resumen de endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/evaluation-templates/` | Lista plantillas de evaluación (ASG Allen Manza, etc.) con pilares y KPIs |
| POST | `/api/evaluations/run/` | Ejecuta evaluación ASG sobre un proyecto |
| GET | `/api/evaluations/runs/` | Lista ejecuciones con filtros |
| GET | `/api/evaluations/runs/{run_id}/` | Detalle de una ejecución |

## Detalle

### GET /api/evaluation-templates/

Lista todas las plantillas de evaluación disponibles con sus pilares y KPIs.

**Respuesta ejemplo:**
```json
[
  {
    "id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
    "name": "ASG Allen Manza",
    "description": "Evaluación de Instituciones Financieras Intermediarias...",
    "methodology": "ASG Allen Manza",
    "pillars": [
      {
        "id": "...",
        "code": "A",
        "name": "Ambiental",
        "weight": "0.33",
        "kpis": [
          {"id": "...", "code": "A1", "name": "Cambio climático", "max_score": 3}
        ]
      }
    ]
  }
]
```

### POST /api/evaluations/run/

Ejecuta una evaluación ASG sobre un proyecto. Usa RAG + OpenAI para puntuar cada KPI (0-10) con evidencia.

**Body (acepta camelCase o snake_case):**
```json
{
  "projectId": 1,
  "templateId": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"
}
```

**Requisitos:**
- El proyecto debe tener documentos vinculados con chunks procesados (SmartChunk).
- El usuario debe tener permisos de edición sobre el proyecto.

**Respuesta:** El run creado con scores (201 Created).

### GET /api/evaluations/runs/

Lista ejecuciones de evaluaciones con filtros opcionales.

**Query params:**
- `projectId` (int): Filtrar por proyecto
- `templateId` (UUID): Filtrar por plantilla
- `runId` (UUID): Obtener un run específico

**Ejemplos:**
- `GET /api/evaluations/runs/?projectId=1` - Todas las evaluaciones del proyecto 1
- `GET /api/evaluations/runs/?projectId=1&templateId=a1b2c3d4-...` - Evaluaciones del proyecto 1 con plantilla ASG
- `GET /api/evaluations/runs/?runId=uuid` - Detalle de un run

**Respuesta:** Lista de runs con `scores` por KPI.

## Migraciones

```bash
python manage.py migrate evaluation
```

Esto crea las tablas `evaluation_templates`, `evaluation_pillars`, `evaluation_kpis`, `template_evaluation_runs`, `template_evaluation_run_scores` y ejecuta el seed de la plantilla ASG Allen Manza.
