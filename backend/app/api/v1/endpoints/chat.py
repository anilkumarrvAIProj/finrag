"""
Chat API — Fund-aware, user-aware, history-aware
=================================================
Three-tier pipeline:
  Tier 1: Pre-defined structured queries (positions, fees, AUM)
  Tier 2: Text-to-SQL for ad-hoc structured queries
  Tier 3: RAG — fund-scoped if fund_id provided, else tenant-wide
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, TokenPayload
from app.db.session import get_db
from app.models.models import ChatSession, ChatMessage, AuditAction, Fund
from app.schemas.schemas import ChatQueryRequest, ChatSessionDetail, ChatSessionSummary, MessageResponse
from app.services.chat.chat_orchestrator import chat_stream, web_search
from app.services.chat.response_formatter import (
    detect_query_type, format_structured_response,
    clean_preamble, strip_inline_sources, enforce_table_format, apply_response_title,
)
from app.services.retrieval.structured_query import (
    query_top_positions, query_fund_metrics,
    query_personnel_changes, query_qoq_sentiment,
)
from app.services.retrieval.text_to_sql import (
    query_to_sql, execute_sql_query, format_sql_results, should_use_sql,
)
from app.services.audit_service import write_audit_log
from app.core.config import settings

router = APIRouter()
DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/query")
async def query(
    body: ChatQueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    tenant_id = uuid.UUID(current_user.tenant_id)
    user_id = uuid.UUID(current_user.sub)

    # Session management
    session_id = body.session_id
    if session_id:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = ChatSession(
            id=uuid.uuid4(), tenant_id=tenant_id,
            user_id=user_id, title=body.query[:60],
        )
        db.add(session)
        await db.flush()
        session_id = session.id

    # Load history
    history_result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at).limit(20)
    )
    history = [{"role": m.role, "content": m.content} for m in history_result.scalars().all()]

    # Save user message
    db.add(ChatMessage(id=uuid.uuid4(), session_id=session_id, role="user", content=body.query))
    await db.commit()

    # Fund-scoped retrieval — look up Weaviate collection for this fund
    fund_collection = None
    fund_id_for_session = getattr(body, 'fund_id', None)
    if fund_id_for_session:
        fund_result = await db.execute(
            select(Fund).where(Fund.id == fund_id_for_session, Fund.tenant_id == tenant_id)
        )
        fund = fund_result.scalar_one_or_none()
        if fund and fund.weaviate_collection:
            fund_collection = fund.weaviate_collection

    query_type, fund_hint = detect_query_type(body.query)

    async def event_generator():
        full_response = ""
        citations = []
        web_sources_list = []

        # ── Tier 1: Pre-defined structured queries ────────────────────────────
        structured_data = None

        if query_type in ("top_positions", "top_positions_qoq"):
            yield _sse("status", {"message": "Fetching positions from database..."})
            structured_data = await query_top_positions(db, fund_hint, compare_qoq=(query_type == "top_positions_qoq"), tenant_id=tenant_id)
        elif query_type == "fees":
            yield _sse("status", {"message": "Fetching fee data..."})
            structured_data = await query_fund_metrics(db, fund_hint, "fees", tenant_id)
        elif query_type == "liquidity":
            yield _sse("status", {"message": "Fetching liquidity terms..."})
            structured_data = await query_fund_metrics(db, fund_hint, "liquidity", tenant_id)
        elif query_type == "aum":
            yield _sse("status", {"message": "Fetching AUM..."})
            structured_data = await query_fund_metrics(db, fund_hint, "aum", tenant_id)
        elif query_type == "performance":
            yield _sse("status", {"message": "Fetching performance metrics..."})
            structured_data = await query_fund_metrics(db, fund_hint, "performance", tenant_id)
            if body.enable_web_search and any(k in body.query.lower() for k in ["s&p", "sp500", "benchmark", "index"]):
                yield _sse("status", {"message": "Fetching benchmark from web..."})
                _, web_sources_list = await web_search(f"S&P 500 performance {(structured_data or {}).get('period', 'latest')}")
        elif query_type == "personnel":
            yield _sse("status", {"message": "Fetching personnel changes..."})
            structured_data = await query_personnel_changes(db, fund_hint, tenant_id=tenant_id)
        elif query_type == "qoq_history":
            yield _sse("status", {"message": "Fetching quarterly history..."})
            structured_data = await query_qoq_sentiment(db, fund_hint, tenant_id=tenant_id)

        if structured_data:
            fund_name = structured_data.get("fund_name", fund_hint or "Fund")
            qt = query_type.replace("_qoq", "")
            formatted = format_structured_response(
                data=structured_data, query_type=qt, fund_name=fund_name,
                web_sources=web_sources_list, rag_citations=citations,
            )
            yield _sse("retrieval_complete", {"chunks_found": 0, "intent": query_type, "citations": []})
            for token in formatted:
                full_response += token
                yield _sse("token", {"text": token})

        # ── Tier 2: Text-to-SQL ───────────────────────────────────────────────
        elif should_use_sql(body.query):
            yield _sse("status", {"message": "Translating to database query..."})
            try:
                sql = await query_to_sql(body.query, settings)
                if sql:
                    yield _sse("status", {"message": "Executing query..."})
                    rows = await execute_sql_query(sql, db)
                    formatted = format_sql_results(rows, body.query)
                    if rows and "not available" not in formatted.lower():
                        yield _sse("retrieval_complete", {"chunks_found": len(rows), "intent": "sql_query", "citations": []})
                        for token in formatted:
                            full_response += token
                            yield _sse("token", {"text": token})
            except Exception:
                pass  # fall through to RAG

        # ── Tier 3: RAG (fund-scoped if fund assigned) ────────────────────────
        if not full_response:
            doc_ids_str = [str(d) for d in body.doc_ids] if body.doc_ids else None
            web_context = None

            if body.enable_web_search and settings.tavily_api_key:
                yield _sse("status", {"message": "Searching the web..."})
                web_context, web_sources_list = await web_search(body.query)

            async for event_str in chat_stream(
                query=body.query,
                tenant_id=str(tenant_id),
                history=history,
                doc_ids=doc_ids_str,
                doc_type_filter=body.doc_type_filter.value if body.doc_type_filter else None,
                fund_collection=fund_collection,
                enable_web_search=body.enable_web_search,
                output_format=body.output_format.value,
            ):
                yield event_str
                if event_str.startswith("event: done"):
                    data_line = [l for l in event_str.split("\n") if l.startswith("data:")]
                    if data_line:
                        try:
                            raw = data_line[0][5:].strip()
                            if not raw:
                                continue
                            data = json.loads(raw)
                            full_response = data.get("full_response", "")
                            raw_citations = data.get("citations", [])
                            # Filter citations by relevance score
                            if raw_citations:
                                top_score = max((c.get("relevance_score", 1.0) for c in raw_citations), default=1.0)
                                citations = [c for c in raw_citations if c.get("relevance_score", top_score) >= top_score * 0.80]
                            web_sources_list = data.get("web_sources", [])
                        except Exception:
                            pass
                continue

        # ── Post-process ──────────────────────────────────────────────────────
        full_response = clean_preamble(full_response)
        full_response = strip_inline_sources(full_response)
        full_response = enforce_table_format(full_response, body.query)
        full_response = apply_response_title(full_response, body.query)

        # ── Save + audit ──────────────────────────────────────────────────────
        async with db.begin():
            db.add(ChatMessage(
                id=uuid.uuid4(), session_id=session_id, role="assistant",
                content=full_response, citations=citations,
                web_search_used=bool(web_sources_list),
            ))
            # Update session last_active
            await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            await write_audit_log(
                db=db, tenant_id=tenant_id, action=AuditAction.QUERY,
                user_id=user_id,
                resource_type="chat_session", resource_id=str(session_id),
                ip_address=request.client.host if request.client else None,
                details={"query_type": query_type, "fund": fund_hint, "query_preview": body.query[:80]},
            )

        yield _sse("done", {
            "citations": citations,
            "web_sources": web_sources_list,
            "web_search_used": bool(web_sources_list),
            "full_response": full_response,
            "intent": query_type,
            "session_id": str(session_id),
        })

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-ID": str(session_id)},
    )


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Return all chat sessions for the current user — for history sidebar."""
    user_id = uuid.UUID(current_user.sub)
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(desc(ChatSession.last_active_at))
        .limit(50)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "title": s.title or "Untitled",
            "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
            "fund_id": str(s.fund_id) if s.fund_id else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Load full message history for a session."""
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    messages = msgs.scalars().all()
    return {
        "session_id": str(session_id),
        "title": session.title,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "web_search_used": m.web_search_used,
            }
            for m in messages
        ],
    }


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return MessageResponse(message="Session deleted")


@router.get("/quick-questions")
async def get_quick_questions(
    fund_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Return quick questions — fund-specific if fund_id provided, else tenant defaults."""
    if fund_id:
        result = await db.execute(
            select(Fund).where(Fund.id == fund_id, Fund.tenant_id == uuid.UUID(current_user.tenant_id))
        )
        fund = result.scalar_one_or_none()
        if fund and fund.quick_questions:
            return {"questions": fund.quick_questions}

    # Default quick questions
    return {
        "questions": [
            "What are the top 5 positions?",
            "What is the 1yr performance vs benchmark?",
            "What are the management and performance fees?",
            "What is the current AUM and liquidity terms?",
        ]
    }
