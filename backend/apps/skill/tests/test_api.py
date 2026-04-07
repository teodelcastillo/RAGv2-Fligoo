from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


User = get_user_model()


class SkillAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="secret123",
            username="owner",
        )
        self.client.force_authenticate(self.user)

    def test_create_skill_sets_hybrid_retrieval_for_comparative_mode(self):
        payload = {
            "name": "Comparative Goals",
            "description": "Compare goals by document",
            "skill_type": "quick",
            "allowed_contexts": ["project"],
            "system_prompt": "Use evidence only.",
            "prompt_template": "Analyze docs\n\n{{context}}",
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "comparative_mode_enabled": True,
            "strict_missing_evidence": True,
            "retrieval_strategy": "global",
            "k_per_doc": 2,
            "total_limit": 10,
            "max_per_doc_after_rerank": 3,
        }
        response = self.client.post(reverse("skill-list"), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["retrieval_strategy"], "hybrid_per_document")
        self.assertTrue(response.data["comparative_mode_enabled"])
