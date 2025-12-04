from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

User = get_user_model()


class TokenService:
    """Utility helpers for uid/token workflows (password reset, email verification)."""

    token_generator = PasswordResetTokenGenerator()

    @staticmethod
    def make_uid(user: User) -> str:
        return urlsafe_base64_encode(force_bytes(user.pk))

    @classmethod
    def decode_uid(cls, uid: str):
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            return User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return None

    @classmethod
    def generate_token(cls, user: User) -> str:
        return cls.token_generator.make_token(user)

    @classmethod
    def validate_token(cls, uid: str, token: str):
        user = cls.decode_uid(uid)
        if user and cls.token_generator.check_token(user, token):
            return user
        return None

