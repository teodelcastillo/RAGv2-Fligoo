from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.skill.models import (
    ExecutionOutputMode,
    ExecutionStatus,
    RetrievalStrategy,
    Skill,
    SkillContext,
    SkillExecution,
    SkillStep,
    SkillType,
)

User = get_user_model()

ALLOWED_CONTEXT_VALUES = {c.value for c in SkillContext}
MULTI_DOCUMENT_CONTEXTS = {SkillContext.REPOSITORY.value, SkillContext.PROJECT.value}
DOCUMENT_FIRST_KEYWORDS = (
    "compar",
    "versus",
    "vs ",
    "benchmark",
    "checklist",
    "extract",
    "snapshot",
    "map",
    "diagnosis",
    "table",
    "matriz",
    "criter",
)
TABLE_COLUMN_TYPES = {"text", "boolean", "number", "enum", "date"}


def _requires_document_first_analysis(
    *,
    skill_type: str,
    allowed_contexts: list[str],
    name: str,
    description: str,
    prompt_template: str,
) -> bool:
    has_multi_document_scope = bool(set(allowed_contexts or []).intersection(MULTI_DOCUMENT_CONTEXTS))
    if not has_multi_document_scope:
        return False
    if skill_type == SkillType.COPILOT:
        return True
    text = f"{name} {description} {prompt_template}".lower()
    return any(keyword in text for keyword in DOCUMENT_FIRST_KEYWORDS)


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

class SkillStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillStep
        fields = ("id", "title", "instructions", "position")


class SkillSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True, allow_null=True)
    steps = SkillStepSerializer(many=True, read_only=True)

    class Meta:
        model = Skill
        fields = (
            "id", "slug", "name", "description", "skill_type",
            "allowed_contexts", "system_prompt", "prompt_template",
            "model", "temperature",
            "comparative_mode_enabled", "strict_missing_evidence",
            "retrieval_strategy", "k_per_doc", "total_limit", "max_per_doc_after_rerank",
            "is_template", "is_default_enabled",
            "owner", "owner_email", "steps",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "slug", "is_template", "is_default_enabled",
            "owner", "owner_email", "created_at", "updated_at",
        )


class SkillStepWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    instructions = serializers.CharField()
    position = serializers.IntegerField(min_value=1)


class SkillWriteSerializer(serializers.ModelSerializer):
    steps = SkillStepWriteSerializer(many=True, required=False)

    class Meta:
        model = Skill
        fields = (
            "name", "description", "skill_type",
            "allowed_contexts", "system_prompt", "prompt_template",
            "model", "temperature",
            "comparative_mode_enabled", "strict_missing_evidence",
            "retrieval_strategy", "k_per_doc", "total_limit", "max_per_doc_after_rerank",
            "steps",
        )

    def validate_allowed_contexts(self, value):
        if not value:
            raise serializers.ValidationError("At least one allowed context is required.")
        invalid = set(value) - ALLOWED_CONTEXT_VALUES
        if invalid:
            raise serializers.ValidationError(
                f"Invalid values: {sorted(invalid)}. "
                f"Allowed: {sorted(ALLOWED_CONTEXT_VALUES)}."
            )
        return value

    def validate(self, attrs):
        existing = self.instance
        skill_type = attrs.get(
            "skill_type",
            existing.skill_type if existing else SkillType.QUICK,
        )
        steps = attrs.get("steps", [])
        allowed_contexts = attrs.get(
            "allowed_contexts",
            existing.allowed_contexts if existing else [],
        )
        comparative_mode_enabled = attrs.get(
            "comparative_mode_enabled",
            existing.comparative_mode_enabled if existing else False,
        )
        retrieval_strategy = attrs.get(
            "retrieval_strategy",
            existing.retrieval_strategy if existing else RetrievalStrategy.GLOBAL,
        )
        k_per_doc = attrs.get("k_per_doc", existing.k_per_doc if existing else 2)
        total_limit = attrs.get("total_limit", existing.total_limit if existing else 12)
        max_per_doc_after_rerank = attrs.get(
            "max_per_doc_after_rerank",
            existing.max_per_doc_after_rerank if existing else 4,
        )

        if skill_type == SkillType.COPILOT and not steps:
            raise serializers.ValidationError(
                {"steps": "Copilot skills require at least one step."}
            )
        effective_prompt_template = attrs.get(
            "prompt_template",
            existing.prompt_template if existing else "",
        )
        name = attrs.get("name", existing.name if existing else "")
        description = attrs.get("description", existing.description if existing else "")

        if _requires_document_first_analysis(
            skill_type=skill_type,
            allowed_contexts=allowed_contexts,
            name=name,
            description=description,
            prompt_template=effective_prompt_template,
        ):
            comparative_mode_enabled = True
            attrs["comparative_mode_enabled"] = True
            attrs["retrieval_strategy"] = RetrievalStrategy.HYBRID_PER_DOCUMENT
        if skill_type == SkillType.QUICK and not effective_prompt_template.strip():
            raise serializers.ValidationError(
                {"prompt_template": "Quick skills require a prompt template."}
            )
        if retrieval_strategy not in {choice for choice, _ in RetrievalStrategy.choices}:
            raise serializers.ValidationError(
                {"retrieval_strategy": "Invalid retrieval strategy."}
            )
        if k_per_doc < 1 or k_per_doc > 10:
            raise serializers.ValidationError(
                {"k_per_doc": "k_per_doc must be between 1 and 10."}
            )
        if total_limit < 1 or total_limit > 50:
            raise serializers.ValidationError(
                {"total_limit": "total_limit must be between 1 and 50."}
            )
        if max_per_doc_after_rerank < 1 or max_per_doc_after_rerank > 20:
            raise serializers.ValidationError(
                {
                    "max_per_doc_after_rerank": (
                        "max_per_doc_after_rerank must be between 1 and 20."
                    )
                }
            )
        if max_per_doc_after_rerank > total_limit:
            raise serializers.ValidationError(
                {
                    "max_per_doc_after_rerank": (
                        "max_per_doc_after_rerank cannot exceed total_limit."
                    )
                }
            )
        if comparative_mode_enabled and retrieval_strategy == RetrievalStrategy.GLOBAL:
            attrs["retrieval_strategy"] = RetrievalStrategy.HYBRID_PER_DOCUMENT
        return attrs

    def create(self, validated_data):
        steps_data = validated_data.pop("steps", [])
        skill = Skill.objects.create(**validated_data)
        for step in steps_data:
            SkillStep.objects.create(skill=skill, **step)
        return skill

    def update(self, instance, validated_data):
        steps_data = validated_data.pop("steps", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if steps_data is not None:
            instance.steps.all().delete()
            for step in steps_data:
                SkillStep.objects.create(skill=instance, **step)
        return instance


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class SkillExecutionSerializer(serializers.ModelSerializer):
    skill_name = serializers.CharField(source="skill.name", read_only=True)
    skill_type = serializers.CharField(source="skill.skill_type", read_only=True)
    context_label = serializers.CharField(read_only=True)
    # Resolve context slugs for the frontend
    repository_slug = serializers.SlugField(source="repository.slug", read_only=True, allow_null=True)
    project_slug = serializers.SlugField(source="project.slug", read_only=True, allow_null=True)
    document_slug = serializers.SlugField(source="document.slug", read_only=True, allow_null=True)

    class Meta:
        model = SkillExecution
        fields = (
            "id", "skill", "skill_name", "skill_type",
            "status", "context_label",
            "repository_slug", "project_slug", "document_slug",
            "extra_instructions", "output_mode",
            "output", "output_structured",
            "document_snapshot", "metadata", "error_message",
            "started_at", "finished_at", "created_at",
        )
        read_only_fields = fields


class RunSkillSerializer(serializers.Serializer):
    """Input for POST /api/skills/{slug}/run/"""
    context_type = serializers.ChoiceField(
        choices=["repository", "project", "document"],
        required=True,
    )
    context_slug = serializers.SlugField(required=True)
    extra_instructions = serializers.CharField(required=False, allow_blank=True, default="")
    output_mode = serializers.ChoiceField(
        choices=ExecutionOutputMode.choices,
        required=False,
        default=ExecutionOutputMode.TEXT,
    )
    table_schema = serializers.DictField(required=False)
    table_columns = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        allow_empty=False,
    )

    def validate(self, attrs):
        context_type = attrs["context_type"]
        context_slug = attrs["context_slug"]

        if context_type == "repository":
            from apps.repository.models import Repository
            try:
                attrs["repository"] = Repository.objects.for_user(
                    self.context["request"].user
                ).get(slug=context_slug)
            except Repository.DoesNotExist:
                raise serializers.ValidationError({"context_slug": "Repository not found."})

        elif context_type == "project":
            from apps.project.models import Project
            try:
                attrs["project"] = Project.objects.for_user(
                    self.context["request"].user
                ).get(slug=context_slug)
            except Project.DoesNotExist:
                raise serializers.ValidationError({"context_slug": "Project not found."})

        elif context_type == "document":
            from apps.document.models import Document
            try:
                attrs["document"] = Document.objects.get(slug=context_slug)
            except Document.DoesNotExist:
                raise serializers.ValidationError({"context_slug": "Document not found."})

        output_mode = attrs.get("output_mode", ExecutionOutputMode.TEXT)
        table_schema = attrs.get("table_schema") or {}
        table_columns = attrs.get("table_columns") or []

        if table_schema and not table_columns:
            table_columns = table_schema.get("columns", [])
            attrs["table_columns"] = table_columns

        if output_mode == ExecutionOutputMode.TABLE and not table_columns:
            raise serializers.ValidationError(
                {"table_columns": "table_columns is required when output_mode='table'."}
            )
        if output_mode != ExecutionOutputMode.TABLE and (table_columns or table_schema):
            raise serializers.ValidationError(
                {"table_schema": "table schema fields can only be used with output_mode='table'."}
            )
        if output_mode == ExecutionOutputMode.TABLE:
            attrs["table_schema"] = self._build_table_schema(table_schema, table_columns)
        return attrs

    def _build_table_schema(self, table_schema: dict, table_columns: list[str]) -> dict:
        columns = table_schema.get("columns") if table_schema else None
        if not columns:
            columns = [{"key": c, "label": c, "type": "text"} for c in table_columns]
        if not isinstance(columns, list):
            raise serializers.ValidationError({"table_schema": "columns must be a list."})

        normalized_columns = []
        seen_keys = set()
        for raw in columns:
            if isinstance(raw, str):
                raw = {"key": raw, "label": raw, "type": "text"}
            if not isinstance(raw, dict):
                raise serializers.ValidationError({"table_schema": "Invalid column entry."})
            key = (raw.get("key") or "").strip()
            label = (raw.get("label") or key).strip()
            col_type = (raw.get("type") or "text").strip().lower()
            prompt_hint = (raw.get("prompt_hint") or "").strip()
            required = bool(raw.get("required", False))
            allowed_values = raw.get("allowed_values") or []

            if not key:
                raise serializers.ValidationError({"table_schema": "Every column must include a key."})
            if key in seen_keys:
                raise serializers.ValidationError({"table_schema": f"Duplicate column key: {key}"})
            if col_type not in TABLE_COLUMN_TYPES:
                raise serializers.ValidationError(
                    {"table_schema": f"Invalid type for column '{key}': {col_type}"}
                )
            if col_type == "enum":
                if not isinstance(allowed_values, list) or len(allowed_values) == 0:
                    raise serializers.ValidationError(
                        {"table_schema": f"Column '{key}' of type enum requires allowed_values."}
                    )
                allowed_values = [str(v).strip() for v in allowed_values if str(v).strip()]
                if not allowed_values:
                    raise serializers.ValidationError(
                        {"table_schema": f"Column '{key}' of type enum requires non-empty allowed_values."}
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
            "name": (table_schema.get("name") or "").strip(),
            "description": (table_schema.get("description") or "").strip(),
            "columns": normalized_columns,
        }
