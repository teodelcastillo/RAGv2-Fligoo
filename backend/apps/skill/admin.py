from django.contrib import admin

from apps.skill.models import Skill, SkillExecution, SkillStep


class SkillStepInline(admin.TabularInline):
    model = SkillStep
    extra = 0
    fields = ("position", "title", "instructions")


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "skill_type", "owner", "is_template", "created_at")
    list_filter = ("skill_type", "is_template")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SkillStepInline]


@admin.register(SkillExecution)
class SkillExecutionAdmin(admin.ModelAdmin):
    list_display = ("id", "skill", "owner", "status", "created_at", "finished_at")
    list_filter = ("status", "skill__skill_type")
    readonly_fields = ("output", "output_structured", "metadata", "document_snapshot")
