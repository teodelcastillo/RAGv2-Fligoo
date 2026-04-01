from django.contrib import admin

from apps.repository.models import Repository, RepositoryDocument


class RepositoryDocumentInline(admin.TabularInline):
    model = RepositoryDocument
    extra = 0
    fields = ("document", "is_active", "added_at")
    readonly_fields = ("added_at",)


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ("name", "repo_type", "owner", "category", "created_at")
    list_filter = ("repo_type",)
    search_fields = ("name", "category")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [RepositoryDocumentInline]
