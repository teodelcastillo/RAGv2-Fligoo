from django.urls import path

from apps.authentication.api.views import (
    CustomTokenRefreshView,
    LogoutView,
    MFASetupView,
    MFAVerifyView,
    MFADisableView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    RegisterView,
    TokenObtainPairWithMFAView,
    VerifyEmailView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("login/", TokenObtainPairWithMFAView.as_view(), name="auth-login"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password/reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path(
        "password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("me/", ProfileView.as_view(), name="auth-profile"),
    path("mfa/setup/", MFASetupView.as_view(), name="auth-mfa-setup"),
    path("mfa/verify/", MFAVerifyView.as_view(), name="auth-mfa-verify"),
    path("mfa/disable/", MFADisableView.as_view(), name="auth-mfa-disable"),
]

