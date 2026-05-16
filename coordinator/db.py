"""SQLAlchemy models and engine wiring for the coordinator."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _gen_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Prober(Base):
    __tablename__ = "probers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_id)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProberToken(Base):
    """Tokens that authorize a prober to register and report results.

    Stored alongside the legacy env-var allow-list — auth code checks both.
    """

    __tablename__ = "prober_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_id)
    label: Mapped[str] = mapped_column(String(128), default="")
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_id)
    # pending | claimed | done | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    claimed_by: Mapped[str | None] = mapped_column(String(128), default=None)
    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Total number of links submitted (cached for fast progress queries).
    n_links: Mapped[int] = mapped_column(Integer, default=0)

    outcomes: Mapped[list[Outcome]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    prober_name: Mapped[str] = mapped_column(String(128), index=True)
    link: Mapped[str] = mapped_column(Text)
    protocol: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    server: Mapped[str | None] = mapped_column(String(255), default=None)
    port: Mapped[int | None] = mapped_column(Integer, default=None)
    ok: Mapped[bool] = mapped_column(default=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    engine_startup_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    job: Mapped[Job] = relationship(back_populates="outcomes")


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self._engine: AsyncEngine = create_async_engine(url, future=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        # Make sure SQLite file's directory exists.
        if self.url.startswith("sqlite"):
            path = self.url.split("///")[-1]
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations: add columns that newer code expects but old
        # databases may not have.  SQLite ignores 'IF NOT EXISTS' for columns,
        # so we check schema first.
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            cols = await conn.execute(text("PRAGMA table_info(jobs)"))
            existing = {row[1] for row in cols.fetchall()} if self.url.startswith("sqlite") else set()
            if existing and "n_links" not in existing:
                await conn.execute(text("ALTER TABLE jobs ADD COLUMN n_links INTEGER DEFAULT 0"))

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    async def dispose(self) -> None:
        await self._engine.dispose()


__all__ = ["Base", "Database", "Job", "Outcome", "Prober", "ProberToken", "select"]
