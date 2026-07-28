from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UTCDateTime
from engine.table_names import resolve_table


class InboxDocument(Base):
    __tablename__ = resolve_table("inbox_documents", "inbox_documents")

    # BIGINT 自增主键（对齐生产外部建表；spec 3 2026-07-28 修订六，不再使用 UUID）
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    creator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    send_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    participants: Mapped[str] = mapped_column(Text, nullable=False)
    cc_recipients: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_urls: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    fwd: Mapped[int] = mapped_column(Integer, default=0)
    skip: Mapped[int] = mapped_column(Integer, default=0)
    forward_time: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    def __init__(self, **kwargs):
        kwargs.setdefault("attachment_urls", "[]")
        kwargs.setdefault("fwd", 0)
        kwargs.setdefault("skip", 0)
        super().__init__(**kwargs)
