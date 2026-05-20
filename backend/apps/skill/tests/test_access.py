from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.project.models import Project, ProjectShareRole
from apps.repository.models import Repository, RepositoryShareRole, RepositoryType
from apps.skill.models import ExecutionStatus, Skill, SkillExecution, SkillType

User = get_user_model()


class SkillExecutionAccessTestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="secret123", username="owner"
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", password="secret123", username="viewer"
        )
        self.skill = Skill.objects.create(
            name="Shared Output Skill",
            slug="shared-output-skill",
            skill_type=SkillType.QUICK,
            allowed_contexts=["project", "repository"],
            owner=self.owner,
        )

    def test_shared_project_execution_visible_in_global_list(self):
        project = Project.objects.create(owner=self.owner, name="Shared Project")
        project.shares.create(user=self.viewer, role=ProjectShareRole.VIEWER)
        execution = SkillExecution.objects.create(
            skill=self.skill,
            owner=self.owner,
            project=project,
            status=ExecutionStatus.COMPLETED,
        )

        self.client.force_authenticate(self.viewer)
        url = reverse("skill-execution-list")
        response = self.client.get(url, {"project": project.slug})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], execution.id)

    def test_shared_repository_execution_visible_in_global_list(self):
        repo = Repository.objects.create(
            owner=self.owner,
            name="Shared Repo",
            repo_type=RepositoryType.PRIVATE,
        )
        repo.shares.create(user=self.viewer, role=RepositoryShareRole.VIEWER)
        execution = SkillExecution.objects.create(
            skill=self.skill,
            owner=self.owner,
            repository=repo,
            status=ExecutionStatus.COMPLETED,
        )

        self.client.force_authenticate(self.viewer)
        url = reverse("skill-execution-list")
        response = self.client.get(url, {"repository": repo.slug})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], execution.id)

    def test_collaborator_cannot_delete_owner_execution(self):
        project = Project.objects.create(owner=self.owner, name="Shared Delete")
        project.shares.create(user=self.viewer, role=ProjectShareRole.VIEWER)
        execution = SkillExecution.objects.create(
            skill=self.skill,
            owner=self.owner,
            project=project,
            status=ExecutionStatus.COMPLETED,
        )

        self.client.force_authenticate(self.viewer)
        url = reverse("skill-execution-detail", kwargs={"pk": execution.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_run_skill_on_shared_project(self):
        project = Project.objects.create(owner=self.owner, name="Shared Run")
        project.shares.create(user=self.viewer, role=ProjectShareRole.VIEWER)
        project.enabled_skills.add(self.skill)

        self.client.force_authenticate(self.viewer)
        url = reverse("skill-run", kwargs={"slug": self.skill.slug})
        response = self.client.post(
            url,
            {"context_type": "project", "context_slug": project.slug},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("context_slug", response.data)
