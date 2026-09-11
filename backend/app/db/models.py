"""Database models for contracts and their extracted review data."""

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contract_status"),
        default=ContractStatus.uploaded,
        index=True,
    )
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    chunks: Mapped[list["ContractChunk"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    obligations: Mapped[list["Obligation"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    risks: Mapped[list["Risk"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )


class ContractChunk(Base):
    __tablename__ = "contract_chunks"
    __table_args__ = (
        UniqueConstraint("contract_id", "chunk_index", name="uq_contract_chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    contract: Mapped[Contract] = relationship(back_populates="chunks")


class Obligation(Base):
    __tablename__ = "obligations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    responsible_party: Mapped[str | None] = mapped_column(String(255))
    due_date: Mapped[date | None] = mapped_column(Date)
    source_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    contract: Mapped[Contract] = relationship(back_populates="obligations")


class Risk(Base):
    __tablename__ = "risks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level"), index=True
    )
    score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    contract: Mapped[Contract] = relationship(back_populates="risks")
