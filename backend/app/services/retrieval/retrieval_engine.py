"""
Retrieval Engine — Fund-Aware
=============================
When a fund_id is provided, searches ONLY that fund's Weaviate collection.
Falls back to shared collection for cross-fund queries.
Citation filtering keeps only high-relevance documents.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.embedding.embedding_service import embed_single
from app.services.embedding.weaviate_client import bm25_search, semantic_search
from app.services.fund_service import semantic_search_fund, bm25_search_fund

logger = get_logger(__name__)


class QueryIntent(str, Enum):
    SUMMARY = "summary"
    COMPARISON = "comparison"
    PERSONNEL = "personnel"
    TEMPORAL = "temporal"
    METRIC = "metric"
    GENERAL = "general"


@dataclass
class RetrievedChunk:
    weaviate_id: str
    document_id: str
    content: str
    chunk_type: str
    section_title: Optional[str]
    page_start: int
    page_end: int
    doc_type: str
    fund_name: Optional[str]
    report_date: Optional[str]
    filename: str
    rrf_score: float = 0.0
    rerank_score: float = 0.0


@dataclass
class RetrievalResult:
    query: str
    intent: QueryIntent
    chunks: list[RetrievedChunk]
    citations: list[dict]
    context_text: str
    total_tokens: int


INTENT_PATTERNS = {
    QueryIntent.COMPARISON: [r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b", r"\bdifference\b", r"\bboth\b.*\bfund", r"\bcontrast\b"],
    QueryIntent.PERSONNEL: [r"\bpersonnel\b", r"\bmanager\b", r"\bstaff\b", r"\bappointment\b", r"\bresign\b", r"\bjoin\b", r"\bteam\b"],
    QueryIntent.TEMPORAL: [r"\bq[1-4]\b", r"\bquarter\b", r"\byear\b", r"\b20\d{2}\b", r"\blatest\b", r"\brecent\b", r"\btrend\b"],
    QueryIntent.METRIC: [r"\baum\b", r"\bnav\b", r"\breturn\b", r"\bperformance\b", r"\balpha\b", r"\bbeta\b", r"\bsharpe\b"],
    QueryIntent.SUMMARY: [r"\bsummar\b", r"\boverview\b", r"\bdescribe\b", r"\bwhat is\b", r"\btell me about\b"],
}


def classify_intent(query: str) -> QueryIntent:
    q = query.lower()
    scores = {intent: sum(1 for p in patterns if re.search(p, q)) for intent, patterns in INTENT_PATTERNS.items()}
    best = max(scores, key=lambda k: scores[k])
    return QueryIntent.GENERAL if scores[best] == 0 else best


def reciprocal_rank_fusion(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            wid = item["weaviate_id"]
            scores[wid] = scores.get(wid, 0.0) + 1.0 / (k + rank + 1)
            items[wid] = item
    return [dict(items[wid], rrf_score=scores[wid]) for wid in sorted(scores, key=lambda x: scores[x], reverse=True)]


def rerank(candidates: list[dict], top_k: int) -> list[dict]:
    return sorted(candidates, key=lambda x: x.get("rrf_score", 0), reverse=True)[:top_k]


def _build_citations(chunks: list[dict], score_threshold_pct: float = 0.80) -> list[dict]:
    """Only cite documents with RRF score >= 80% of top chunk score."""
    if not chunks:
        return []

    top_score = max(c.get("rrf_score", 0) for c in chunks)
    min_score = top_score * score_threshold_pct

    doc_best: dict[str, float] = {}
    doc_info: dict[str, dict] = {}

    for chunk in chunks:
        doc_id = chunk.get("document_id", "")
        score = chunk.get("rrf_score", 0)
        if doc_id not in doc_best or score > doc_best[doc_id]:
            doc_best[doc_id] = score
            doc_info[doc_id] = chunk

    qualifying = sorted(
        [(doc_id, s) for doc_id, s in doc_best.items() if s >= min_score],
        key=lambda x: x[1], reverse=True,
    )

    citations = []
    for ref_num, (doc_id, score) in enumerate(qualifying, 1):
        chunk = doc_info[doc_id]
        citations.append({
            "ref": ref_num,
            "document_id": doc_id,
            "filename": chunk.get("filename", "Unknown"),
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "section_title": chunk.get("section_title"),
            "relevance_score": round(score, 4),
        })

    logger.info("Citations", total=len(chunks), qualifying=len(qualifying), top=round(top_score, 4))
    return citations


def assemble_context(chunks: list[dict], max_tokens: int = 8000) -> tuple[str, list[dict]]:
    context_parts = []
    total_tokens = 0
    used_chunks = []

    for i, chunk in enumerate(chunks):
        chunk_tokens = chunk.get("token_count", 200)
        if total_tokens + chunk_tokens > max_tokens:
            break
        header = (
            f"[{i+1}] {chunk.get('filename', 'Unknown')} "
            f"| Page {chunk.get('page_start', '?')} "
            f"| {chunk.get('section_title') or chunk.get('doc_type', '')}"
        )
        context_parts.append(f"{header}\n{chunk['content']}")
        total_tokens += chunk_tokens
        used_chunks.append(chunk)

    return "\n\n---\n\n".join(context_parts), _build_citations(used_chunks)


async def retrieve(
    query: str,
    tenant_id: str,
    doc_ids: Optional[list[str]] = None,
    doc_type_filter: Optional[str] = None,
    fund_collection: Optional[str] = None,   # Phase 2: fund-scoped search
    top_k_retrieve: int = None,
    top_k_rerank: int = None,
) -> RetrievalResult:
    """
    Hybrid retrieval with optional fund isolation.
    If fund_collection is provided, searches ONLY that fund's collection.
    Otherwise falls back to the shared tenant collection.
    """
    top_k_retrieve = top_k_retrieve or settings.top_k_retrieve
    top_k_rerank = top_k_rerank or settings.top_k_rerank

    intent = classify_intent(query)
    logger.info("Retrieval", intent=intent.value, fund_scoped=bool(fund_collection))

    query_vector = await embed_single(query)

    if fund_collection:
        # Fund-scoped search — complete isolation
        vector_results = semantic_search_fund(query_vector, fund_collection, top_k=top_k_retrieve)
        bm25_results = bm25_search_fund(query, fund_collection, top_k=top_k_retrieve)
    else:
        # Shared collection — filtered by tenant
        vector_results = semantic_search(query_vector, tenant_id, doc_type_filter, doc_ids, top_k_retrieve)
        bm25_results = bm25_search(query, tenant_id, doc_type_filter, doc_ids, top_k_retrieve)

    logger.info("Raw results", vector=len(vector_results), bm25=len(bm25_results))

    fused = reciprocal_rank_fusion([vector_results, bm25_results])
    reranked = rerank(fused, top_k=top_k_rerank)
    context_text, citations = assemble_context(reranked)

    chunks = [
        RetrievedChunk(
            weaviate_id=c.get("weaviate_id", ""),
            document_id=c.get("document_id", ""),
            content=c.get("content", ""),
            chunk_type=c.get("chunk_type", "text"),
            section_title=c.get("section_title"),
            page_start=c.get("page_start", 0),
            page_end=c.get("page_end", 0),
            doc_type=c.get("doc_type", ""),
            fund_name=c.get("fund_name"),
            report_date=c.get("report_date"),
            filename=c.get("filename", ""),
            rrf_score=c.get("rrf_score", 0.0),
        )
        for c in reranked
    ]

    return RetrievalResult(
        query=query, intent=intent, chunks=chunks, citations=citations,
        context_text=context_text,
        total_tokens=sum(c.get("token_count", 0) for c in reranked),
    )
