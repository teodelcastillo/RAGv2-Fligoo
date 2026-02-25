"""Celery task for async ASG evaluation (optional)."""

from __future__ import annotations

try:
    from celery import shared_task
except ImportError:
    shared_task = None

from django.contrib.auth import get_user_model

User = get_user_model()


def run_asg_evaluation_sync(project_id: int, template_id: str, user_id: int) -> str:
    """Synchronous ASG evaluation - returns run id."""
    from apps.evaluation.services_asg import execute_asg_evaluation_sync

    user = User.objects.get(pk=user_id)
    run = execute_asg_evaluation_sync(project_id=project_id, template_id=template_id, user=user)
    return str(run.id)


if shared_task:

    @shared_task(name="evaluation.asg_run")
    def run_asg_evaluation_task(project_id: int, template_id: str, user_id: int):
        return run_asg_evaluation_sync(project_id, template_id, user_id)

else:

    class _ASGEvalTask:
        def delay(self, project_id: int, template_id: str, user_id: int):
            return run_asg_evaluation_sync(project_id, template_id, user_id)

    run_asg_evaluation_task = _ASGEvalTask()
