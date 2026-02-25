from django.contrib import admin

from apps.chat.models import ChatSession, ChatMessage


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "created_at", "is_active")
    search_fields = ("title", "owner__email", "owner__username")
    list_filter = ("is_active", "model", "temperature")
    filter_horizontal = ("allowed_documents",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("content", "session__title", "session__owner__email")
    autocomplete_fields = ("session",)























