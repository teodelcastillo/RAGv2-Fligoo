import pyotp
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authentication.services.tokens import TokenService

User = get_user_model()


class AuthenticationAPITestCase(APITestCase):
    def setUp(self):
        self.password = "StrongPass123!"
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user@example.com",
            password=self.password,
        )

    def test_register_creates_user_and_sends_email(self):
        url = reverse("auth-register")
        payload = {
            "email": "new@example.com",
            "password": "AnotherPass123!",
            "first_name": "New",
            "last_name": "User",
        }

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Confirma tu email", mail.outbox[0].subject)

    def test_login_requires_email_verification(self):
        url = reverse("auth-login")
        payload = {"email": self.user.email, "password": self.password}

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Email no verificado", response.data["detail"])

    def test_login_succeeds_once_verified(self):
        self.user.email_verified = True
        self.user.save(update_fields=["email_verified"])

        url = reverse("auth-login")
        payload = {"email": self.user.email, "password": self.password}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertTrue(response.data["user"]["email_verified"])

    def test_mfa_requires_otp(self):
        secret = pyotp.random_base32()
        self.user.email_verified = True
        self.user.mfa_secret = secret
        self.user.mfa_enabled = True
        self.user.save(update_fields=["email_verified", "mfa_secret", "mfa_enabled"])

        url = reverse("auth-login")
        payload = {"email": self.user.email, "password": self.password}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        payload["otp"] = pyotp.TOTP(secret).now()
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_password_reset_flow_updates_password(self):
        self.user.email_verified = True
        self.user.save(update_fields=["email_verified"])

        request_url = reverse("auth-password-reset")
        self.client.post(request_url, {"email": self.user.email}, format="json")

        uid = TokenService.make_uid(self.user)
        token = TokenService.generate_token(self.user)
        confirm_url = reverse("auth-password-reset-confirm")
        payload = {"uid": uid, "token": token, "new_password": "BrandNewPass123!"}
        response = self.client.post(confirm_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass123!"))

    def test_password_change_endpoint(self):
        self.user.email_verified = True
        self.user.save(update_fields=["email_verified"])
        self.client.force_authenticate(user=self.user)

        url = reverse("auth-password-change")
        payload = {"old_password": self.password, "new_password": "EvenStronger123!"}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("EvenStronger123!"))

