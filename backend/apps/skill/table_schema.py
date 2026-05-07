"""
Centralized validation and normalization for TableSchema definitions.

A TableSchema is a JSON document used by Skills, SkillSteps and SkillExecutions
to drive structured tabular outputs. Keeping the parser/normalizer in one
module ensures the contract stays consistent across:

- `Skill.table_schema`               (skill-level default)
- `SkillStep.table_schema`           (per-step in copilots)
- `SkillExecution.metadata.table_schema` (effective schema used at run time)
- API payloads (`SkillWriteSerializer`, `RunSkillSerializer`).
"""
from __future__ import annotations

from typing import Any


TABLE_COLUMN_TYPES: set[str] = {"text", "boolean", "number", "enum", "date"}


class TableSchemaError(ValueError):
    """Raised when a table schema cannot be normalized."""


def normalize_table_schema(raw: Any) -> dict:
    """
    Validate and normalize a table schema payload.

    Returns a dict with stable shape:
        {
            "name": str,
            "description": str,
            "columns": [
                {
                    "key": str,
                    "label": str,
                    "type": "text" | "boolean" | "number" | "enum" | "date",
                    "required": bool,
                    "prompt_hint": str,
                    "allowed_values": list[str],
                },
                ...
            ],
        }

    Raises:
        TableSchemaError: when the schema is missing required fields or has
            invalid values (duplicate keys, missing enum values, etc.).
    """
    if raw in (None, "", {}):
        raise TableSchemaError("Table schema is required.")
    if not isinstance(raw, dict):
        raise TableSchemaError("Table schema must be an object.")

    columns_raw = raw.get("columns")
    if not isinstance(columns_raw, list) or len(columns_raw) == 0:
        raise TableSchemaError("Table schema must include a non-empty 'columns' list.")

    normalized_columns: list[dict] = []
    seen_keys: set[str] = set()

    for entry in columns_raw:
        if isinstance(entry, str):
            entry = {"key": entry, "label": entry, "type": "text"}
        if not isinstance(entry, dict):
            raise TableSchemaError("Invalid column entry.")

        key = str(entry.get("key", "")).strip()
        label = str(entry.get("label", key) or key).strip()
        col_type = str(entry.get("type", "text") or "text").strip().lower()
        prompt_hint = str(entry.get("prompt_hint", "") or "").strip()
        required = bool(entry.get("required", False))
        allowed_values = entry.get("allowed_values") or []

        if not key:
            raise TableSchemaError("Every column must include a non-empty key.")
        if key in seen_keys:
            raise TableSchemaError(f"Duplicate column key: {key}")
        if col_type not in TABLE_COLUMN_TYPES:
            raise TableSchemaError(
                f"Invalid type for column '{key}': {col_type}. "
                f"Allowed: {sorted(TABLE_COLUMN_TYPES)}."
            )

        if col_type == "enum":
            if not isinstance(allowed_values, list):
                raise TableSchemaError(
                    f"Column '{key}' of type enum requires an allowed_values list."
                )
            allowed_values = [str(v).strip() for v in allowed_values if str(v).strip()]
            if not allowed_values:
                raise TableSchemaError(
                    f"Column '{key}' of type enum requires non-empty allowed_values."
                )
        else:
            allowed_values = []

        seen_keys.add(key)
        normalized_columns.append(
            {
                "key": key,
                "label": label,
                "type": col_type,
                "required": required,
                "prompt_hint": prompt_hint,
                "allowed_values": allowed_values,
            }
        )

    return {
        "name": str(raw.get("name", "") or "").strip(),
        "description": str(raw.get("description", "") or "").strip(),
        "columns": normalized_columns,
    }


def is_table_schema_valid(raw: Any) -> bool:
    """Return True if `raw` can be normalized as a valid table schema."""
    try:
        normalize_table_schema(raw)
    except TableSchemaError:
        return False
    return True


def schema_has_columns(schema: Any) -> bool:
    """Lightweight check for a populated schema (without raising)."""
    if not isinstance(schema, dict):
        return False
    columns = schema.get("columns")
    return isinstance(columns, list) and len(columns) > 0
