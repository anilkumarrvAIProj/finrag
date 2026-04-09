"""
Structured Financial Data Models
Extracted from documents and stored in PostgreSQL for exact retrieval.
Complements vector search for precise numerical queries.
"""
import uuid
from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, Date, ForeignKey, Index, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class Fund(Base):
    """One record per fund/manager across all documents."""
    __tablename__ = "funds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_name: Mapped[Optional[str]] = mapped_column(String(255))
    strategy: Mapped[Optional[str]] = mapped_column(String(255))   # Long/Short, Global Macro, etc.
    inception_date: Mapped[Optional[date]] = mapped_column(Date)
    domicile: Mapped[Optional[str]] = mapped_column(String(100))
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    weaviate_namespace: Mapped[Optional[str]] = mapped_column(String(255))

    snapshots: Mapped[list["FundSnapshot"]] = relationship(back_populates="fund")
    positions: Mapped[list["FundPosition"]] = relationship(back_populates="fund")
    personnel: Mapped[list["PersonnelChange"]] = relationship(back_populates="fund")

    __table_args__ = (
        Index("ix_funds_tenant", "tenant_id"),
        Index("ix_funds_name", "fund_name"),
    )


class FundSnapshot(Base):
    """Point-in-time financial metrics — one row per fund per reporting period."""
    __tablename__ = "fund_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    report_date: Mapped[Optional[date]] = mapped_column(Date)
    period: Mapped[Optional[str]] = mapped_column(String(20))   # Q1 2025, Jan 2025, etc.

    # AUM
    aum_usd: Mapped[Optional[float]] = mapped_column(Float)
    aum_raw: Mapped[Optional[str]] = mapped_column(String(50))   # original string e.g. "$4.2B"

    # Performance
    return_mtd: Mapped[Optional[float]] = mapped_column(Float)
    return_qtd: Mapped[Optional[float]] = mapped_column(Float)
    return_ytd: Mapped[Optional[float]] = mapped_column(Float)
    return_1yr: Mapped[Optional[float]] = mapped_column(Float)
    return_3yr: Mapped[Optional[float]] = mapped_column(Float)
    return_5yr: Mapped[Optional[float]] = mapped_column(Float)
    return_inception: Mapped[Optional[float]] = mapped_column(Float)

    # Risk metrics
    volatility: Mapped[Optional[float]] = mapped_column(Float)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float)
    beta: Mapped[Optional[float]] = mapped_column(Float)
    calmar_ratio: Mapped[Optional[float]] = mapped_column(Float)

    # Terms
    management_fee: Mapped[Optional[float]] = mapped_column(Float)
    performance_fee: Mapped[Optional[float]] = mapped_column(Float)
    hurdle_rate: Mapped[Optional[float]] = mapped_column(Float)
    liquidity_terms: Mapped[Optional[str]] = mapped_column(String(255))
    lockup_period: Mapped[Optional[str]] = mapped_column(String(100))
    redemption_notice: Mapped[Optional[str]] = mapped_column(String(100))

    # Benchmark
    benchmark_name: Mapped[Optional[str]] = mapped_column(String(100))
    benchmark_return_1yr: Mapped[Optional[float]] = mapped_column(Float)

    fund: Mapped["Fund"] = relationship(back_populates="snapshots")

    __table_args__ = (
        Index("ix_snapshots_fund", "fund_id"),
        Index("ix_snapshots_date", "report_date"),
    )


class FundPosition(Base):
    """Top holdings/positions — extracted from fact sheets and exposure reports."""
    __tablename__ = "fund_positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    report_date: Mapped[Optional[date]] = mapped_column(Date)
    period: Mapped[Optional[str]] = mapped_column(String(20))

    position_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[Optional[str]] = mapped_column(String(20))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    asset_class: Mapped[Optional[str]] = mapped_column(String(100))
    direction: Mapped[Optional[str]] = mapped_column(String(10))   # long / short
    weight_pct: Mapped[Optional[float]] = mapped_column(Float)     # % of portfolio
    rank: Mapped[Optional[int]] = mapped_column(Integer)           # 1 = top position

    fund: Mapped["Fund"] = relationship(back_populates="positions")

    __table_args__ = (
        Index("ix_positions_fund_date", "fund_id", "report_date"),
    )


class PersonnelChange(Base):
    """Key personnel changes — extracted from DDQ and quarterly letters."""
    __tablename__ = "personnel_changes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    previous_role: Mapped[Optional[str]] = mapped_column(String(255))
    new_role: Mapped[Optional[str]] = mapped_column(String(255))
    change_type: Mapped[Optional[str]] = mapped_column(String(50))  # joined / left / promoted
    effective_date: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    fund: Mapped["Fund"] = relationship(back_populates="personnel")

    __table_args__ = (Index("ix_personnel_fund", "fund_id"),)


class FundRawData(Base):
    """Generic storage for Excel sheets that don't match known schemas."""
    __tablename__ = "fund_raw_data"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[Optional[list]] = mapped_column(JSONB)   # raw rows as JSON

    __table_args__ = (Index("ix_raw_data_fund", "fund_id"),)
