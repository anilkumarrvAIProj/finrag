"""
SQLAlchemy ORM models — plain String columns, no PostgreSQL enum types.
"""
import uuid
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class DocumentType(str, enum.Enum):
    FACT_SHEET = "fact_sheet"
    INVESTMENT_REPORT = "investment_report"
    QUARTERLY_REPORT = "quarterly_report"
    PERSONNEL = "personnel"
    PORTFOLIO_SUMMARY = "portfolio_summary"
    OTHER = "other"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    OCR_PROCESSING = "ocr_processing"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"
    DEGRADED = "degraded"


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    ANALYST = "analyst"
    READ_ONLY = "read_only"


class AuditAction(str, enum.Enum):
    UPLOAD = "upload"
    REPROCESS = "reprocess"
    DELETE = "delete"
    QUERY = "query"
    LOGIN = "login"
    LOGOUT = "logout"
    ROLE_CHANGE = "role_change"
    EXPORT = "export"
    REGISTER = "register"
    PASSWORD_CHANGE = "password_change"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Quick questions config for chat UI
    quick_questions: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    documents: Mapped[list["Document"]] = relationship(back_populates="tenant")
    funds: Mapped[list["Fund"]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))  # bcrypt hash
    role: Mapped[str] = mapped_column(String(32), default="read_only", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")

    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id"),
        Index("ix_users_tenant_id", "tenant_id"),
        Index("ix_users_email_tenant", "email", "tenant_id"),
    )


class Fund(Base):
    """One record per fund — central entity for Phase 2 fund isolation."""
    __tablename__ = "funds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Weaviate collection name for this fund's chunks
    weaviate_collection: Mapped[Optional[str]] = mapped_column(String(255))
    # Quick questions specific to this fund
    quick_questions: Mapped[Optional[list]] = mapped_column(JSONB)
    fund_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)

    tenant: Mapped["Tenant"] = relationship(back_populates="funds")
    documents: Mapped[list["Document"]] = relationship(back_populates="fund")

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug"),
        Index("ix_funds_tenant", "tenant_id"),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    fund_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id"), nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), default="other")
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    s3_raw_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    s3_processed_key: Mapped[Optional[str]] = mapped_column(String(1024))
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    fund_name: Mapped[Optional[str]] = mapped_column(String(512))
    report_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float)
    language: Mapped[Optional[str]] = mapped_column(String(10))
    extracted_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    weaviate_namespace: Mapped[Optional[str]] = mapped_column(String(255))
    chunk_count: Mapped[Optional[int]] = mapped_column(Integer)

    tenant: Mapped["Tenant"] = relationship(back_populates="documents")
    fund: Mapped[Optional["Fund"]] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[Optional[int]] = mapped_column(Integer)
    page_end: Mapped[Optional[int]] = mapped_column(Integer)
    section_title: Mapped[Optional[str]] = mapped_column(String(512))
    chunk_type: Mapped[str] = mapped_column(String(32), default="text")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    weaviate_id: Mapped[Optional[str]] = mapped_column(String(64))

    document: Mapped["Document"] = relationship(back_populates="chunks")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    fund_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("funds.id"), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    doc_filter: Mapped[Optional[list]] = mapped_column(JSONB)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Optional[list]] = mapped_column(JSONB)
    retrieval_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    web_search_used: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(128))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(512))
    details: Mapped[Optional[dict]] = mapped_column(JSONB)
    hmac_chain: Mapped[Optional[str]] = mapped_column(String(64))
