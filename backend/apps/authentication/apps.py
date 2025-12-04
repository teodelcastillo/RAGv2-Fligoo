from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authentication"

    def ready(self):
        # Import signals for token invalidation side-effects
        from apps.authentication import signals  # noqa: F401

