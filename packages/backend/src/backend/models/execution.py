from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class TaskExecution(Base):
    __tablename__ = "task_executions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"))
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedules.id"), nullable=True
    )
    trigger_type: Mapped[str] = mapped_column(
        Enum("scheduled", "api", "manual", name="execution_trigger_type")
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "success", "failed", "cancelled", name="execution_status"),
        default="pending",
    )
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    pipeline = relationship("Pipeline", back_populates="executions")
    schedule = relationship("Schedule", back_populates="executions")
    logs = relationship("TaskLog", back_populates="execution")
    artifacts = relationship("TaskArtifact", back_populates="execution")


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("task_executions.id"))
    timestamp: Mapped[datetime] = mapped_column(MySQLDateTime(fsp=6), server_default=func.now())
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

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("task_executions.id"))
    file_name: Mapped[str] = mapped_column(String(500))
    minio_key: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    execution = relationship("TaskExecution", back_populates="artifacts")
