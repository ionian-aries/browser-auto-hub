import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


def _generate_uuid() -> str:
    return str(uuid.uuid4())


class InboxDocument(Base):
    __tablename__ = "inbox_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
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
    forward_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(self, **kwargs):
        kwargs.setdefault("attachment_urls", "[]")
        kwargs.setdefault("fwd", 0)
        kwargs.setdefault("skip", 0)
        super().__init__(**kwargs)
