from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.logger import StepLogger


@dataclass
class ExecutionContext:
    """Injected by runner — provides pipeline access to platform infrastructure."""

    logger: StepLogger
    db: Any  # AsyncSession (typed as Any to avoid backend import)
    minio: Any  # MinioStorage (typed as Any to avoid backend import)
    settings: Any  # Settings (typed as Any to avoid backend import)
    execution_id: str
