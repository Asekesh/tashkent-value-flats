from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ScrapeTask(Base):
    __tablename__ = "scrape_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    trigger: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="quick")
    sources: Mapped[str] = mapped_column(String(200), default="")
    current_source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
