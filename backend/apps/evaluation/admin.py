from django.contrib import admin

from apps.evaluation.models import (
    Evaluation,
    EvaluationDocument,
    EvaluationMetric,
    EvaluationPillar,
    EvaluationRun,
    EvaluationShare,
    MetricEvaluationResult,
    PillarEvaluationResult,
)


class EvaluationDocumentInline(admin.TabularInline):
    model = EvaluationDocument
    extra = 0
    autocomplete_fields = ("document",)


class EvaluationPillarInline(admin.StackedInline):
    model = EvaluationPillar
    extra = 0
    show_change_link = True
    fields = ("title", "position", "context_instructions")


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "visibility", "project", "created_at")
    list_filter = ("visibility", "created_at", "is_active")
    search_fields = ("title", "slug", "owner__email")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (EvaluationDocumentInline, EvaluationPillarInline)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EvaluationShare)
class EvaluationShareAdmin(admin.ModelAdmin):
    list_display = ("evaluation", "user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("evaluation__title", "user__email")


@admin.register(EvaluationPillar)
class EvaluationPillarAdmin(admin.ModelAdmin):
    list_display = ("title", "evaluation", "position")
    list_filter = ("evaluation",)
    ordering = ("evaluation", "position")


@admin.register(EvaluationMetric)
class EvaluationMetricAdmin(admin.ModelAdmin):
    list_display = ("title", "pillar", "response_type", "position")
    list_filter = ("response_type",)
    ordering = ("pillar", "position")


@admin.register(EvaluationRun)
class EvaluationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "evaluation", "owner", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("evaluation__title", "owner__email")


@admin.register(PillarEvaluationResult)
class PillarEvaluationResultAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "pillar", "position")
    ordering = ("run", "position")


@admin.register(MetricEvaluationResult)
class MetricEvaluationResultAdmin(admin.ModelAdmin):
    list_display = ("id", "pillar_result", "metric", "position")
    ordering = ("pillar_result", "position")

