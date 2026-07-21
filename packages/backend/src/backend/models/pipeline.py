import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


def _generate_uuid() -> str:
    return str(uuid.uuid4())


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_modes: Mapped[dict] = mapped_column(JSON, default=list)
    config_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", name="pipeline_status"), default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    schedules = relationship("Schedule", back_populates="pipeline")
    executions = relationship("TaskExecution", back_populates="pipeline")

    def __init__(self, **kwargs):
        kwargs.setdefault("max_concurrent", 1)
        kwargs.setdefault("timeout_seconds", 3600)
        kwargs.setdefault("status", "active")
        kwargs.setdefault("description", "")
        kwargs.setdefault("trigger_modes", [])
        super().__init__(**kwargs)
