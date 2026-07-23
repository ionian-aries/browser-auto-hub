from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UTCDateTime


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        UTCDateTime, server_default=func.utc_timestamp(), onupdate=func.utc_timestamp()
    )
