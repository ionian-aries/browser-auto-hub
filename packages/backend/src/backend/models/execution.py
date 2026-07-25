from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UTCDateTime, UTCDateTimeFsp, generate_uuid


class TaskExecution(Base):
    __tablename__ = "task_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    pipeline_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipelines.id"))
    schedule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schedules.id"), nullable=True
    )
    trigger_type: Mapped[str] = mapped_column(
        Enum("scheduled", "api", "manual", name="execution_trigger_type")
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", "cancelled", name="execution_status"),
        default="pending",
    )
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 触发时 pipeline 版本快照（spec 1 §4.5）：历史执行可溯「当时跑的是哪版」
    pipeline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.utc_timestamp()
    )

    pipeline = relationship("Pipeline", back_populates="executions")
    schedule = relationship("Schedule", back_populates="executions")
    logs = relationship("TaskLog", back_populates="execution")
    artifacts = relationship("TaskArtifact", back_populates="execution")

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "pending")
        kwargs.setdefault("retry_count", 0)
        super().__init__(**kwargs)


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    execution_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_executions.id"))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTimeFsp, server_default=func.utc_timestamp())
    level: Mapped[str] = mapped_column(
        Enum("info", "warn", "error", name="log_level"), default="info"
    )
    step_name: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    screenshot_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    execution = relationship("TaskExecution", back_populates="logs")


class TaskArtifact(Base):
    __tablename__ = "task_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    execution_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_executions.id"))
    file_name: Mapped[str] = mapped_column(String(500))
    minio_key: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.utc_timestamp()
    )

    execution = relationship("TaskExecution", back_populates="artifacts")
