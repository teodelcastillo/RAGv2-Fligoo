from django.contrib import admin

from apps.project.models import Project, ProjectDocument, ProjectShare


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "slug", "owner__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProjectDocument)
class ProjectDocumentAdmin(admin.ModelAdmin):
    list_display = ("project", "document", "added_by", "is_primary", "created_at")
    list_filter = ("is_primary", "created_at")
    search_fields = ("project__name", "document__name", "document__slug")


@admin.register(ProjectShare)
class ProjectShareAdmin(admin.ModelAdmin):
    list_display = ("project", "user", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("project__name", "user__email")

