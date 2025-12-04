from django.conf import settings

import pyotp


class MFAService:
    """Manages TOTP secrets and verifications."""

    @staticmethod
    def generate_secret() -> str:
        return pyotp.random_base32()

    @staticmethod
    def provisioning_uri(email: str, secret: str) -> str:
        issuer = getattr(settings, "MFA_ISSUER_NAME", "Ecofilia")
        return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)

    @staticmethod
    def verify(user, code: str) -> bool:
        if not user.mfa_secret:
            return False
        totp = pyotp.TOTP(user.mfa_secret)
        return totp.verify(code, valid_window=1)

