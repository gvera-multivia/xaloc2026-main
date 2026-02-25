from __future__ import annotations

from core.worker_execution.models import ProcessOutcome
from core.worker_execution.task_orchestrator import process_task
from core.worker_execution.utils import extract_expediente_number


def _extraer_n_expediente(payload: dict) -> str:
    return extract_expediente_number(payload)


__all__ = ["ProcessOutcome", "process_task", "_extraer_n_expediente"]
