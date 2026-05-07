from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from django.db.models import QuerySet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas  (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_SEARCH_MORE_CONTEXT: dict = {
    "type": "function",
    "function": {
        "name": "search_more_context",
        "description": (
            "Search for additional relevant document excerpts on a specific topic. "
            "Use this when the provided context is insufficient or you need more "
            "detail on a particular aspect before answering."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Specific search query to find relevant document sections.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of additional excerpts to retrieve (1–8). Default 4.",
                    "default": 4,
                },
            },
            "required": ["query"],
        },
    },
}

TOOL_CALCULATE_GHG: dict = {
    "type": "function",
    "function": {
        "name": "calculate_ghg_emissions",
        "description": (
            "Calculate greenhouse gas emissions from activity data and an emission factor. "
            "Returns the result in tCO2e (tonnes of CO2 equivalent). "
            "Use this instead of performing arithmetic in your response text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "activity_data": {
                    "type": "number",
                    "description": "Activity data value (e.g. kWh, litres of fuel, km driven).",
                },
                "emission_factor": {
                    "type": "number",
                    "description": "Emission factor in tCO2e per unit of activity data.",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of activity data (e.g. kWh, litres, km, tonnes).",
                },
                "scope": {
                    "type": "string",
                    "enum": ["scope_1", "scope_2", "scope_3", "unknown"],
                    "description": "GHG Protocol scope of the emission.",
                    "default": "unknown",
                },
                "description": {
                    "type": "string",
                    "description": "Brief label for the emission source being calculated.",
                    "default": "",
                },
            },
            "required": ["activity_data", "emission_factor", "unit"],
        },
    },
}

TOOL_GET_DOCUMENT_LIST: dict = {
    "type": "function",
    "function": {
        "name": "get_document_list",
        "description": (
            "Return the list of documents available in the current context. "
            "Use this to understand what sources exist before deciding which "
            "ones to search further."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

ALL_TOOLS: list[dict] = [
    TOOL_SEARCH_MORE_CONTEXT,
    TOOL_CALCULATE_GHG,
    TOOL_GET_DOCUMENT_LIST,
]


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------

@dataclass
class SkillToolContext:
    """
    Carries the runtime dependencies that tool executors need.
    Passed through the tool-call loop in generate_with_tools.
    """
    user: Any
    allowed_documents: QuerySet
    # Collects every chunk retrieved by tool calls so callers can record usage.
    additional_chunks: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual tool executors
# ---------------------------------------------------------------------------

def _execute_search_more_context(args: dict, ctx: SkillToolContext) -> str:
    from apps.chat.services.rag import build_context_block, fetch_relevant_chunks

    query = (args.get("query") or "").strip()
    if not query:
        return "Error: 'query' parameter is required."

    top_n = min(max(int(args.get("top_n", 4)), 1), 8)

    try:
        chunks = fetch_relevant_chunks(
            user=ctx.user,
            query_text=query,
            allowed_documents=ctx.allowed_documents,
            top_n=top_n,
            retrieval_strategy="global",
        )
    except Exception as exc:
        logger.warning("search_more_context tool failed: %s", exc)
        return f"Search failed: {exc}"

    ctx.additional_chunks.extend(chunks)
    if not chunks:
        return "No additional relevant excerpts found for this query."
    return build_context_block(chunks)


def _execute_calculate_ghg(args: dict, ctx: SkillToolContext) -> str:
    try:
        activity_data = float(args["activity_data"])
        emission_factor = float(args["emission_factor"])
        unit = str(args.get("unit", ""))
        scope = str(args.get("scope", "unknown"))
        description = str(args.get("description", ""))
    except (KeyError, ValueError, TypeError) as exc:
        return (
            f"Calculation error: {exc}. "
            "Required parameters: activity_data (number), emission_factor (number), unit (string)."
        )

    result_tco2e = activity_data * emission_factor
    lines = [
        "GHG Calculation Result:",
        f"- Activity data: {activity_data:,.4g} {unit}",
        f"- Emission factor: {emission_factor:,.6g} tCO2e/{unit}",
        f"- Result: {result_tco2e:,.4g} tCO2e",
        f"- Scope: {scope.replace('_', ' ').title()}",
    ]
    if description:
        lines.append(f"- Source: {description}")
    return "\n".join(lines)


def _execute_get_document_list(args: dict, ctx: SkillToolContext) -> str:
    try:
        docs = list(ctx.allowed_documents.only("id", "name", "slug"))
    except Exception as exc:
        logger.warning("get_document_list tool failed: %s", exc)
        return f"Failed to retrieve document list: {exc}"

    if not docs:
        return "No documents available in the current context."
    lines = [f"Available documents ({len(docs)}):"]
    for doc in docs:
        lines.append(f"- [{doc.slug}] {doc.name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_TOOL_EXECUTORS: dict[str, Callable[[dict, SkillToolContext], str]] = {
    "search_more_context": _execute_search_more_context,
    "calculate_ghg_emissions": _execute_calculate_ghg,
    "get_document_list": _execute_get_document_list,
}


def execute_tool(tool_name: str, tool_args_json: str, ctx: SkillToolContext) -> str:
    """
    Dispatch a single tool call by name.

    Returns a plain-text result string to be injected back into the
    conversation as a tool-role message.
    """
    executor = _TOOL_EXECUTORS.get(tool_name)
    if executor is None:
        return f"Unknown tool '{tool_name}'. Available: {', '.join(_TOOL_EXECUTORS)}."
    try:
        args = json.loads(tool_args_json) if tool_args_json else {}
    except json.JSONDecodeError:
        return f"Invalid JSON arguments for tool '{tool_name}'."
    return executor(args, ctx)
