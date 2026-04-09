"""
Pydantic v2 request/response schemas for all API endpoints.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class DocTypeEnum(str, Enum):
    FACT_SHEET = "fact_sheet"
    INVESTMENT_REPORT = "investment_report"
    QUARTERLY_REPORT = "quarterly_report"
    PERSONNEL = "personnel"
    PORTFOLIO_SUMMARY = "portfolio_summary"
    OTHER = "other"


class DocStatusEnum(str, Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    OCR_PROCESSING = "ocr_processing"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"
    DEGRADED = "degraded"


class OutputFormatEnum(str, Enum):
    PARAGRAPH = "paragraph"
    BULLETS = "bullets"
    TABLE = "table"


# ─── Document Schemas ─────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocStatusEnum
    doc_type: DocTypeEnum
    sha256_hash: str
    file_size_bytes: int
    version: int
    created_at: datetime
    message: str = "Upload accepted. Processing has started."

    model_config = {"from_attributes": True}


class DocumentDetail(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    sha256_hash: str
    doc_type: DocTypeEnum
    status: DocStatusEnum
    version: int
    is_latest: bool
    file_size_bytes: int
    page_count: Optional[int]
    fund_name: Optional[str]
    report_date: Optional[datetime]
    is_scanned: bool
    ocr_confidence: Optional[float]
    chunk_count: Optional[int]
    error_message: Optional[str]
    processing_started_at: Optional[datetime]
    processing_completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentDetail]
    total: int
    page: int
    page_size: int


class DocumentReprocessRequest(BaseModel):
    force_ocr: bool = False


# ─── Chat Schemas ─────────────────────────────────────────────────────────────

class ChatQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[uuid.UUID] = None
    doc_ids: Optional[list[uuid.UUID]] = None        # Scope to specific docs
    doc_type_filter: Optional[DocTypeEnum] = None
    enable_web_search: bool = False
    output_format: OutputFormatEnum = OutputFormatEnum.PARAGRAPH

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        # Basic prompt injection guard
        dangerous = ["ignore previous", "system:", "assistant:", "###"]
        lower = v.lower()
        for d in dangerous:
            if d in lower:
                raise ValueError("Query contains disallowed content")
        return v.strip()


class Citation(BaseModel):
    ref: int
    document_id: Optional[str]
    filename: str
    page_start: Optional[int]
    page_end: Optional[int]
    section_title: Optional[str]


class WebSource(BaseModel):
    ref: int
    title: str
    url: str


class ChatSessionSummary(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    last_active_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: Optional[list[Citation]]
    web_search_used: bool
    latency_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionDetail(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    messages: list[ChatMessageOut]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Admin / Monitoring Schemas ───────────────────────────────────────────────

class PipelineHealthResponse(BaseModel):
    status: str   # healthy | degraded | down
    workers: dict[str, Any]
    queue_depths: dict[str, int]
    database: str
    vector_store: str
    cache: str


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    ip_address: Optional[str]
    details: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogResponse(BaseModel):
    items: list[AuditLogEntry]
    total: int


# ─── Auth / User Schemas ──────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(super_admin|admin|analyst|read_only)$")


# ─── Generic ──────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
