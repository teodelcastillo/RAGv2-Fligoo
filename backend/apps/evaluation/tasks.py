from __future__ import annotations

try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    shared_task = None

from apps.evaluation.models import EvaluationRun
from apps.evaluation.services import execute_evaluation_run


def run_evaluation_sync(run_id: int):
    run = EvaluationRun.objects.get(pk=run_id)
    execute_evaluation_run(run)


if shared_task:

    @shared_task(name="evaluation.run")
    def run_evaluation_task(run_id: int):
        run_evaluation_sync(run_id)

else:  # pragma: no cover - fallback when Celery is not installed

    class _SyncEvalTask:
        def delay(self, run_id: int):
            return run_evaluation_sync(run_id)

        __call__ = delay

    run_evaluation_task = _SyncEvalTask()