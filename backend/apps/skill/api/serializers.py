from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.skill.models import ExecutionStatus, Skill, SkillExecution, SkillStep, SkillType

User = get_user_model()


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
            "model", "temperature", "is_template",
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
            "model", "temperature", "steps",
        )

    def validate(self, attrs):
        skill_type = attrs.get("skill_type", SkillType.QUICK)
        steps = attrs.get("steps", [])
        if skill_type == SkillType.COPILOT and not steps:
            raise serializers.ValidationError(
                {"steps": "Copilot skills require at least one step."}
            )
        if skill_type == SkillType.QUICK and not attrs.get("prompt_template", "").strip():
            raise serializers.ValidationError(
                {"prompt_template": "Quick skills require a prompt template."}
            )
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
