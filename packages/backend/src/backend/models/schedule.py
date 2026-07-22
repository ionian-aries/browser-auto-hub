from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UTCDateTime, generate_uuid


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    pipeline_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipelines.id"))
    name: Mapped[str] = mapped_column(String(200))
    trigger_type: Mapped[str] = mapped_column(
        Enum("cron", "interval", "once", name="trigger_type")
    )
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), onupdate=func.now()
    )

    pipeline = relationship("Pipeline", back_populates="schedules")
    executions = relationship("TaskExecution", back_populates="schedule")

    def __init__(self, **kwargs):
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("max_retries", 0)
        kwargs.setdefault("retry_delay_seconds", 60)
        super().__init__(**kwargs)
