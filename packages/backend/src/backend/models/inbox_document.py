from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UTCDateTime, generate_uuid
from engine.table_names import resolve_table


class InboxDocument(Base):
    __tablename__ = resolve_table("inbox_documents", "inbox_documents")

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
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
