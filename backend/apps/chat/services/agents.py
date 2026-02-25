from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple

from django.db import transaction

from apps.chat.models import ChatMessage, ChatSession, MessageRole
from apps.chat.services.rag import (
    MAX_CONTEXT_CHUNKS,
    build_context_block,
    fetch_relevant_chunks,
)
from apps.document.utils.client_openia import generate_chat_completion

logger = logging.getLogger(__name__)


ANALYSIS_MODE_SIMPLE = "simple"
ANALYSIS_MODE_REGULATORY = "regulatory_compliance"
ANALYSIS_MODE_ESG_FINANCIAL = "esg_financial_analysis"

AGENT_CONTEXT_CHUNKS = int(
    os.environ.get("AGENT_CONTEXT_CHUNKS", str(MAX_CONTEXT_CHUNKS))
)
AGENT_MAX_CHUNKS_PER_DOC = int(os.environ.get("AGENT_MAX_CHUNKS_PER_DOC", "2"))


@dataclass
class AgentStep:
    key: str
    description: str
    system_prompt: str
    topics: List[str] | None = None


@dataclass
class TaskPlan:
    mode: str
    original_question: str
    steps: List[AgentStep]


@dataclass
class StepExecutionResult:
    key: str
    answer: str
    chunk_ids: List[int]
    usage: Dict[str, Any]
    latency_seconds: float


def plan_task(
    user,
    session: ChatSession,
    user_message_text: str,
    analysis_mode: str | None = None,
) -> TaskPlan:
    """
    Construye un plan de pasos para el agente en función del modo de análisis.
    """
    mode = analysis_mode or ANALYSIS_MODE_SIMPLE

    if mode == ANALYSIS_MODE_REGULATORY:
        steps = [
            AgentStep(
                key="regulatory_requirements",
                description=(
                    "Identifica y resume los requisitos clave de sostenibilidad/ESG "
                    "relevantes para la pregunta del usuario (por ejemplo CSRD, taxonomía, "
                    "marcos de reporte)."
                ),
                system_prompt=(
                    "Eres un experto en regulación ESG y CSRD. A partir del contexto, "
                    "extrae una lista estructurada de requisitos o temas regulatorios "
                    "clave relevantes para la pregunta del usuario."
                ),
                topics=["csrd", "esg", "regulación", "cumplimiento", "reporte"],
            ),
            AgentStep(
                key="client_evidence",
                description=(
                    "Busca en los documentos del cliente evidencias que respondan a "
                    "cada requisito o tema identificado en el paso anterior."
                ),
                system_prompt=(
                    "Eres un analista de cumplimiento. A partir del contexto del cliente, "
                    "busca evidencias que respondan a los requisitos regulatorios y "
                    "resume el nivel de cumplimiento percibido."
                ),
                topics=["evidencia", "política", "indicador", "emisiones", "riesgo"],
            ),
            AgentStep(
                key="synthesis_regulatory",
                description=(
                    "Sintetiza una matriz de cumplimiento: para cada requisito, indica "
                    "nivel de cumplimiento (alto/medio/bajo), evidencias y gaps."
                ),
                system_prompt=(
                    "Eres un consultor que prepara una matriz de cumplimiento. "
                    "Usa los resultados previos para construir un resumen ejecutivo "
                    "con una matriz de requisitos vs. nivel de cumplimiento, "
                    "evidencias y principales recomendaciones."
                ),
                topics=None,
            ),
        ]
    elif mode == ANALYSIS_MODE_ESG_FINANCIAL:
        steps = [
            AgentStep(
                key="environmental_kpis",
                description=(
                    "Extrae KPIs ambientales clave del cliente (emisiones, consumo, "
                    "residuos, riesgos climáticos, etc.)."
                ),
                system_prompt=(
                    "Eres un analista ESG. Extrae y resume los principales KPIs y "
                    "riesgos ambientales del cliente a partir del contexto."
                ),
                topics=[
                    "emisiones",
                    "huella de carbono",
                    "consumo",
                    "residuos",
                    "riesgo climático",
                ],
            ),
            AgentStep(
                key="financial_kpis",
                description=(
                    "Extrae métricas financieras relevantes (ingresos, EBITDA, CAPEX, "
                    "indicadores de solvencia, etc.)."
                ),
                system_prompt=(
                    "Eres un analista financiero. Extrae y resume las principales "
                    "métricas financieras del cliente a partir del contexto."
                ),
                topics=["ingresos", "ebitda", "capex", "margen", "beneficio"],
            ),
            AgentStep(
                key="synthesis_esg_financial",
                description=(
                    "Relaciona los KPIs ambientales con las métricas financieras y "
                    "explica riesgos y oportunidades clave."
                ),
                system_prompt=(
                    "Eres un consultor que integra ESG y finanzas. A partir de los "
                    "KPIs ambientales y financieros ya extraídos, explica cómo los "
                    "riesgos y oportunidades ESG impactan en el desempeño financiero."
                ),
                topics=None,
            ),
        ]
    else:
        # Modo simple: un solo paso equivalente al flujo actual,
        # se mantiene por compatibilidad aunque normalmente no usemos el agente.
        steps = [
            AgentStep(
                key="single_step",
                description="Responde a la pregunta del usuario usando el contexto disponible.",
                system_prompt=session.system_prompt,
                topics=None,
            )
        ]

    return TaskPlan(mode=mode, original_question=user_message_text, steps=steps)


def _aggregate_usage(step_results: List[StepExecutionResult]) -> Dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for r in step_results:
        usage = r.usage or {}
        for key in totals:
            if key in usage and isinstance(usage[key], int):
                totals[key] += usage[key]
    return totals


def run_plan(
    user,
    session: ChatSession,
    plan: TaskPlan,
) -> Tuple[str, List[StepExecutionResult]]:
    """
    Ejecuta secuencialmente los pasos del plan.
    Devuelve el texto final (último paso) y la lista de resultados intermedios.
    """
    allowed_docs = session.allowed_documents.all()
    step_results: List[StepExecutionResult] = []

    # Resultados intermedios concatenados para pasos de síntesis
    intermediate_summaries: List[str] = []

    for step in plan.steps:
        start = time.perf_counter()

        # Determinar si este paso necesita RAG directo o solo síntesis
        needs_rag = not step.key.startswith("synthesis_")

        context_block = ""
        used_chunks_ids: List[int] = []

        if needs_rag and allowed_docs.exists():
            query_text = f"{plan.original_question}\n\n{step.description}"
            chunks = fetch_relevant_chunks(
                user=user,
                query_text=query_text,
                allowed_documents=allowed_docs,
                top_n=AGENT_CONTEXT_CHUNKS,
                topics=step.topics,
                max_chunks_per_doc=AGENT_MAX_CHUNKS_PER_DOC,
            )
            context_block = build_context_block(chunks)
            used_chunks_ids = [c.id for c in chunks]

        # Construir mensajes para el LLM
        messages = []

        # Prompt base de la sesión
        if session.system_prompt:
            messages.append(
                {
                    "role": MessageRole.SYSTEM,
                    "content": session.system_prompt.strip(),
                }
            )

        # Prompt específico del paso
        messages.append(
            {
                "role": MessageRole.SYSTEM,
                "content": step.system_prompt,
            }
        )

        # Si hay contexto de documentos, agregarlo
        if context_block:
            messages.append(
                {
                    "role": MessageRole.SYSTEM,
                    "content": (
                        "Utiliza el siguiente contexto de documentos para este paso:\n\n"
                        f"{context_block}"
                    ),
                }
            )

        # Añadir resultados intermedios previos para pasos de síntesis
        if step.key.startswith("synthesis_") and intermediate_summaries:
            messages.append(
                {
                    "role": MessageRole.SYSTEM,
                    "content": (
                        "Resultados intermedios de pasos previos:\n\n"
                        + "\n\n---\n\n".join(intermediate_summaries)
                    ),
                }
            )

        # Mensaje del usuario con la pregunta original
        messages.append(
            {
                "role": MessageRole.USER,
                "content": plan.original_question,
            }
        )

        answer_text, usage = generate_chat_completion(
            messages,
            model=session.model,
            temperature=session.temperature,
        )

        latency = time.perf_counter() - start

        step_results.append(
            StepExecutionResult(
                key=step.key,
                answer=answer_text,
                chunk_ids=used_chunks_ids,
                usage=usage,
                latency_seconds=latency,
            )
        )

        # Guardar resumen intermedio para síntesis posteriores
        intermediate_summaries.append(
            f"[Paso {step.key}]\n\n{answer_text}".strip()
        )

        logger.info(
            "Agente de chat ejecutó paso '%s' en modo '%s' con %d chunks (latencia=%.2fs)",
            step.key,
            plan.mode,
            len(used_chunks_ids),
            latency,
        )

    return step_results[-1].answer, step_results


class ChatAgentService:
    """
    Servicio de alto nivel para orquestar interacciones multi-step.
    """

    def __init__(
        self,
        *,
        user,
        session: ChatSession,
        analysis_mode: str,
        question: str,
    ) -> None:
        self.user = user
        self.session = session
        self.analysis_mode = analysis_mode or ANALYSIS_MODE_SIMPLE
        self.question = question

    def run(self) -> Tuple[ChatMessage, ChatMessage]:
        plan = plan_task(
            self.user,
            self.session,
            self.question,
            analysis_mode=self.analysis_mode,
        )

        # Si el modo es simple, delegamos al flujo de un solo paso
        if plan.mode == ANALYSIS_MODE_SIMPLE:
            from apps.chat.services.rag import run_single_step_chat

            return run_single_step_chat(
                user=self.user,
                session=self.session,
                content=self.question,
            )

        logger.info(
            "Iniciando ChatAgentService en modo '%s' con %d pasos.",
            plan.mode,
            len(plan.steps),
        )

        t0 = time.perf_counter()
        final_answer, step_results = run_plan(self.user, self.session, plan)
        total_latency = time.perf_counter() - t0

        aggregated_usage = _aggregate_usage(step_results)
        all_chunk_ids: List[int] = []
        for r in step_results:
            all_chunk_ids.extend(r.chunk_ids)
        # Eliminar duplicados preservando orden
        seen = set()
        unique_chunk_ids: List[int] = []
        for cid in all_chunk_ids:
            if cid not in seen:
                seen.add(cid)
                unique_chunk_ids.append(cid)

        with transaction.atomic():
            user_message = ChatMessage.objects.create(
                session=self.session,
                role=MessageRole.USER,
                content=self.question,
            )

            assistant_metadata: Dict[str, Any] = {
                "usage": aggregated_usage,
                "analysis_mode": plan.mode,
                "agent_plan": {
                    "mode": plan.mode,
                    "steps": [asdict(step) for step in plan.steps],
                },
                "agent_steps": [
                    {
                        "key": r.key,
                        "answer": r.answer,
                        "chunk_ids": r.chunk_ids,
                        "usage": r.usage,
                        "latency_seconds": r.latency_seconds,
                    }
                    for r in step_results
                ],
                "agent_metrics": {
                    "total_steps": len(step_results),
                    "total_latency_seconds": total_latency,
                    "total_chunks": len(unique_chunk_ids),
                },
            }

            assistant_message = ChatMessage.objects.create(
                session=self.session,
                role=MessageRole.ASSISTANT,
                content=final_answer,
                chunk_ids=unique_chunk_ids,
                metadata=assistant_metadata,
            )

        logger.info(
            "ChatAgentService completado en modo '%s' (pasos=%d, latencia_total=%.2fs, chunks=%d).",
            plan.mode,
            len(step_results),
            total_latency,
            len(unique_chunk_ids),
        )

        return user_message, assistant_message


