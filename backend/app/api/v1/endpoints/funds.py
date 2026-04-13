"""
Fund Management API
===================
GET    /funds              — list all funds for tenant
POST   /funds              — create a new fund
GET    /funds/{fund_id}    — get fund details + documents
PATCH  /funds/{fund_id}    — update fund metadata
DELETE /funds/{fund_id}    — deactivate fund
GET    /funds/{fund_id}/documents — list documents in fund
POST   /funds/{fund_id}/quick-questions — set quick questions
"""
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, get_admin_user, TokenPayload
from app.db.session import get_db
from app.models.models import Fund, Document
from app.services.fund_service import ensure_fund_weaviate_collection

router = APIRouter()


class FundCreate(BaseModel):
    name: str
    strategy: Optional[str] = None
    description: Optional[str] = None
    quick_questions: Optional[list[str]] = None


class FundUpdate(BaseModel):
    name: Optional[str] = None
    strategy: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    quick_questions: Optional[list[str]] = None


def _make_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@router.get("")
async def list_funds(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    tenant_id = uuid.UUID(current_user.tenant_id)
    result = await db.execute(
        select(Fund).where(Fund.tenant_id == tenant_id, Fund.is_active == True)
        .order_by(Fund.name)
    )
    funds = result.scalars().all()

    fund_list = []
    for f in funds:
        doc_count = await db.execute(
            select(func.count()).select_from(Document)
            .where(Document.fund_id == f.id, Document.is_latest == True)
        )
        fund_list.append({
            "id": str(f.id),
            "name": f.name,
            "slug": f.slug,
            "strategy": f.strategy,
            "description": f.description,
            "weaviate_collection": f.weaviate_collection,
            "quick_questions": f.quick_questions or [],
            "document_count": doc_count.scalar_one(),
        })
    return fund_list


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_fund(
    body: FundCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    tenant_id = uuid.UUID(current_user.tenant_id)
    slug = _make_slug(body.name)

    # Check slug uniqueness
    existing = await db.execute(
        select(Fund).where(Fund.tenant_id == tenant_id, Fund.slug == slug)
    )
    if existing.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"

    # Create Weaviate collection for this fund
    collection_name = f"Fund_{tenant_id.hex[:8]}_{slug.replace('-', '_')}"

    fund = Fund(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=body.name,
        slug=slug,
        strategy=body.strategy,
        description=body.description,
        quick_questions=body.quick_questions,
        weaviate_collection=collection_name,
        is_active=True,
    )
    db.add(fund)
    await db.flush()

    # Create Weaviate collection
    try:
        await ensure_fund_weaviate_collection(collection_name)
    except Exception as exc:
        pass  # non-fatal — collection created on first document upload

    await db.commit()
    return {
        "id": str(fund.id),
        "name": fund.name,
        "slug": fund.slug,
        "strategy": fund.strategy,
        "weaviate_collection": fund.weaviate_collection,
        "message": "Fund created successfully",
    }


@router.get("/{fund_id}")
async def get_fund(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    result = await db.execute(
        select(Fund).where(
            Fund.id == fund_id,
            Fund.tenant_id == uuid.UUID(current_user.tenant_id),
        )
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    docs_result = await db.execute(
        select(Document).where(Document.fund_id == fund_id, Document.is_latest == True)
        .order_by(Document.created_at.desc()).limit(20)
    )
    docs = docs_result.scalars().all()

    return {
        "id": str(fund.id),
        "name": fund.name,
        "slug": fund.slug,
        "strategy": fund.strategy,
        "description": fund.description,
        "weaviate_collection": fund.weaviate_collection,
        "quick_questions": fund.quick_questions or [],
        "is_active": fund.is_active,
        "documents": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "status": d.status,
                "doc_type": d.doc_type,
                "page_count": d.page_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
    }


@router.patch("/{fund_id}")
async def update_fund(
    fund_id: uuid.UUID,
    body: FundUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(
        select(Fund).where(
            Fund.id == fund_id,
            Fund.tenant_id == uuid.UUID(current_user.tenant_id),
        )
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    if body.name is not None:
        fund.name = body.name
    if body.strategy is not None:
        fund.strategy = body.strategy
    if body.description is not None:
        fund.description = body.description
    if body.is_active is not None:
        fund.is_active = body.is_active
    if body.quick_questions is not None:
        fund.quick_questions = body.quick_questions

    await db.commit()
    return {"message": "Fund updated", "id": str(fund.id)}


@router.delete("/{fund_id}")
async def deactivate_fund(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(
        select(Fund).where(
            Fund.id == fund_id,
            Fund.tenant_id == uuid.UUID(current_user.tenant_id),
        )
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    fund.is_active = False
    await db.commit()
    return {"message": "Fund deactivated"}


@router.post("/{fund_id}/quick-questions")
async def set_quick_questions(
    fund_id: uuid.UUID,
    questions: list[str],
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_admin_user),
):
    result = await db.execute(
        select(Fund).where(Fund.id == fund_id, Fund.tenant_id == uuid.UUID(current_user.tenant_id))
    )
    fund = result.scalar_one_or_none()
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    fund.quick_questions = questions[:8]  # max 8 quick questions
    await db.commit()
    return {"message": "Quick questions updated", "questions": fund.quick_questions}
