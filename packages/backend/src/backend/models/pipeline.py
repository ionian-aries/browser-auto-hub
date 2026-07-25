from datetime import datetime

from sqlalchemy import Enum, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UTCDateTime, generate_uuid


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_modes: Mapped[dict] = mapped_column(JSON, default=list)
    config_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        # archived：代码已删除的软归档（spec 1 §4.5）——列表隐藏/禁止触发/调度跳过/历史保留
        Enum("active", "disabled", "archived", name="pipeline_status"), default="active"
    )
    # 代码声明版本（register_pipeline version 参数），纯溯源标记；
    # sync 按定义字段内容对比决定是否覆盖（spec 1 二十七次修订），不由 version 差异触发
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.utc_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.utc_timestamp(), onupdate=func.utc_timestamp()
    )

    schedules = relationship("Schedule", back_populates="pipeline")
    executions = relationship("TaskExecution", back_populates="pipeline")

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "active")
        kwargs.setdefault("description", "")
        kwargs.setdefault("trigger_modes", [])
        super().__init__(**kwargs)
