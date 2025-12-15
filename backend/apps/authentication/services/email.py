from django.conf import settings
from django.core.mail import send_mail


class EmailService:
    """Thin wrapper around Django's mailer to keep auth flows decoupled."""

    @staticmethod
    def _send(subject: str, message: str, recipient: str) -> None:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )

    @classmethod
    def send_verification_email(cls, user, verification_url: str) -> None:
        subject = "Confirma tu email"
        message = (
            f"Hola {user.first_name or user.email},\n\n"
            f"Confirma tu cuenta haciendo clic en el siguiente enlace:\n{verification_url}\n\n"
            "Si no solicitaste esta acción, ignora este correo."
        )
        cls._send(subject, message, user.email)

    @classmethod
    def send_password_reset_email(cls, user, reset_url: str) -> None:
        subject = "Restablecer contraseña"
        message = (
            f"Hola {user.first_name or user.email},\n\n"
            f"Restablece tu contraseña usando el siguiente enlace:\n{reset_url}\n\n"
            "Si no solicitaste este cambio, contacta al soporte inmediatamente."
        )
        cls._send(subject, message, user.email)

