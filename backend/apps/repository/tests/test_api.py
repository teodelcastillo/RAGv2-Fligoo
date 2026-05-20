from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.repository.models import Repository, RepositoryShareRole, RepositoryType

User = get_user_model()


class RepositoryAPITestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="secret123", username="owner"
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", password="secret123", username="viewer"
        )
        self.client.force_authenticate(self.owner)

    def test_share_management(self):
        repo = Repository.objects.create(
            owner=self.owner,
            name="Private Repo",
            repo_type=RepositoryType.PRIVATE,
        )
        url = reverse("repository-shares", kwargs={"slug": repo.slug})
        payload = {"user_email": self.viewer.email, "role": RepositoryShareRole.EDITOR}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], RepositoryShareRole.EDITOR)

        self.client.force_authenticate(self.viewer)
        detail_url = reverse("repository-detail", kwargs={"slug": repo.slug})
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)

        patch_url = reverse(
            "repository-share-detail",
            kwargs={"slug": repo.slug, "share_id": response.data["id"]},
        )
        self.client.force_authenticate(self.owner)
        patch_response = self.client.patch(
            patch_url,
            {"role": RepositoryShareRole.VIEWER},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data["role"], RepositoryShareRole.VIEWER)
