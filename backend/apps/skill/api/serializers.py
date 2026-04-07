from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.skill.models import (
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
            "is_template",
            "owner", "owner_email", "steps",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "slug", "is_template", "owner", "owner_email", "created_at", "updated_at")


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
        skill_type = attrs.get("skill_type", SkillType.QUICK)
        steps = attrs.get("steps", [])
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
            "extra_instructions",
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

    def validate(self, attrs):
        context_type = attrs["context_type"]
        context_slug = attrs["context_slug"]

        if context_type == "repository":
            from apps.repository.models import Repository
            try:
                attrs["repository"] = Repository.objects.get(slug=context_slug)
            except Repository.DoesNotExist:
                raise serializers.ValidationError({"context_slug": "Repository not found."})

        elif context_type == "project":
            from apps.project.models import Project
            try:
                attrs["project"] = Project.objects.get(slug=context_slug)
            except Project.DoesNotExist:
                raise serializers.ValidationError({"context_slug": "Project not found."})

        elif context_type == "document":
            from apps.document.models import Document
            try:
                attrs["document"] = Document.objects.get(slug=context_slug)
            except Document.DoesNotExist:
                raise serializers.ValidationError({"context_slug": "Document not found."})

        return attrs
