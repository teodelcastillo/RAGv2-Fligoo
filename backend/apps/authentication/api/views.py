from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.authentication.api.serializers import (
    LogoutSerializer,
    MFASetupSerializer,
    MFAVerifySerializer,
    MFADisableSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileSerializer,
    RegisterSerializer,
    TokenObtainPairWithMFASerializer,
    VerifyEmailSerializer,
)
from apps.authentication.services.email import EmailService
from apps.authentication.services.mfa import MFAService
from apps.authentication.services.tokens import TokenService

User = get_user_model()


def build_frontend_url(path: str, params: dict[str, str]) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    query = urlencode(params)
    if query:
        return f"{base}{path}?{query}"
    return f"{base}{path}"


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        uid = TokenService.make_uid(user)
        token = TokenService.generate_token(user)
        verification_url = build_frontend_url("/auth/verify-email", {"uid": uid, "token": token})
        EmailService.send_verification_email(user, verification_url)

        return Response(
            {
                "user": ProfileSerializer(user).data,
                "detail": _("Revisa tu correo para confirmar tu cuenta."),
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = TokenService.validate_token(serializer.validated_data["uid"], serializer.validated_data["token"])
        if not user:
            return Response({"detail": _("Token inválido")}, status=status.HTTP_400_BAD_REQUEST)

        user.mark_email_verified()
        return Response({"detail": _("Email verificado")}, status=status.HTTP_200_OK)


class TokenObtainPairWithMFAView(TokenObtainPairView):
    serializer_class = TokenObtainPairWithMFASerializer
    permission_classes = [AllowAny]


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if user:
            uid = TokenService.make_uid(user)
            token = TokenService.generate_token(user)
            reset_url = build_frontend_url("/auth/reset-password", {"uid": uid, "token": token})
            EmailService.send_password_reset_email(user, reset_url)
        return Response({"detail": _("Si el email existe recibirás instrucciones.")})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = TokenService.validate_token(serializer.validated_data["uid"], serializer.validated_data["token"])
        if not user:
            return Response({"detail": _("Token inválido o expirado.")}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data["new_password"])
        user.mfa_enabled = False
        user.mfa_secret = ""
        user.save(update_fields=["password", "last_password_change", "mfa_enabled", "mfa_secret"])
        return Response({"detail": _("Contraseña actualizada")})


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "last_password_change"])
        return Response({"detail": _("Contraseña actualizada")})


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class MFASetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        secret = MFAService.generate_secret()
        user.mfa_secret = secret
        user.mfa_enabled = False
        user.save(update_fields=["mfa_secret", "mfa_enabled"])
        data = MFASetupSerializer({"secret": secret, "otpauth_url": MFAService.provisioning_uri(user.email, secret)}).data
        return Response(data, status=status.HTTP_201_CREATED)


class MFAVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MFAVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not MFAService.verify(user, serializer.validated_data["code"]):
            return Response({"detail": _("Código MFA inválido")}, status=status.HTTP_400_BAD_REQUEST)
        user.mfa_enabled = True
        user.save(update_fields=["mfa_enabled"])
        return Response({"detail": _("MFA activado")})


class MFADisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MFADisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if user.mfa_enabled and not MFAService.verify(user, serializer.validated_data["code"]):
            return Response({"detail": _("Código MFA inválido")}, status=status.HTTP_400_BAD_REQUEST)
        user.mfa_enabled = False
        user.mfa_secret = ""
        user.save(update_fields=["mfa_enabled", "mfa_secret"])
        return Response({"detail": _("MFA desactivado")})

