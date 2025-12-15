from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.document.models import Document
from apps.project.models import Project, ProjectDocument, ProjectShareRole

User = get_user_model()


class ProjectAPITestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="secret123", username="owner"
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="secret123", username="other"
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", password="secret123", username="viewer"
        )
        self.doc_owned = Document.objects.create(
            owner=self.owner, name="Doc Propio", slug="doc-propio"
        )
        self.doc_public = Document.objects.create(
            owner=self.other,
            name="Doc Público",
            slug="doc-publico",
            is_public=True,
        )
        self.doc_forbidden = Document.objects.create(
            owner=self.other,
            name="Doc Privado",
            slug="doc-privado",
            is_public=False,
        )
        self.client.force_authenticate(self.owner)

    def test_create_project_with_documents(self):
        url = reverse("project-list")
        payload = {
            "name": "Proyecto A",
            "description": "Descripción",
            "document_slugs": ["doc-propio", "doc-publico"],
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["documents"]), 2)

    def test_create_project_rejects_forbidden_document(self):
        url = reverse("project-list")
        payload = {
            "name": "Proyecto B",
            "document_slugs": ["doc-privado"],
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_document_action(self):
        project = Project.objects.create(owner=self.owner, name="Proyecto Base")
        ProjectDocument.objects.create(
            project=project, document=self.doc_owned, added_by=self.owner
        )
        url = reverse("project-add-document", kwargs={"slug": project.slug})
        payload = {"document_slugs": ["doc-publico"]}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {doc["slug"] for doc in response.data["documents"]}
        self.assertSetEqual(slugs, {"doc-propio", "doc-publico"})

    def test_viewer_cannot_modify_documents(self):
        project = Project.objects.create(owner=self.owner, name="Proyecto Compartido")
        project.shares.create(user=self.viewer, role=ProjectShareRole.VIEWER)
        self.client.force_authenticate(self.viewer)
        url = reverse("project-add-document", kwargs={"slug": project.slug})
        response = self.client.post(
            url, {"document_slugs": ["doc-publico"]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_share_management(self):
        project = Project.objects.create(owner=self.owner, name="Proyecto Share")
        url = reverse("project-shares", kwargs={"slug": project.slug})
        payload = {"user_id": self.viewer.id, "role": ProjectShareRole.EDITOR}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], ProjectShareRole.EDITOR)

        list_response = self.client.get(url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)

        share_id = response.data["id"]
        detail_url = reverse(
            "project-share-detail",
            kwargs={"slug": project.slug, "share_id": share_id},
        )
        patch_response = self.client.patch(
            detail_url,
            {"role": ProjectShareRole.VIEWER, "user_id": self.viewer.id},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data["role"], ProjectShareRole.VIEWER)

        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

