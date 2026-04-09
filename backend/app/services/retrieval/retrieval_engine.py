"""
Retrieval Engine
- Hybrid retrieval: dense vector + BM25 sparse
- Reciprocal Rank Fusion (RRF) for result merging
- Score-threshold filtering — only cite documents that genuinely contributed
- Context window assembly with metadata
- Intent-based routing
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.embedding.embedding_service import embed_single
from app.services.embedding.weaviate_client import bm25_search, semantic_search

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


# ── Intent Classifier ─────────────────────────────────────────────────────────

INTENT_PATTERNS = {
    QueryIntent.COMPARISON: [
        r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b", r"\bdifference\b",
        r"\bboth\b.*\bfund", r"\bsimilar\b", r"\bcontrast\b",
    ],
    QueryIntent.PERSONNEL: [
        r"\bpersonnel\b", r"\bmanager\b", r"\bstaff\b", r"\bappointment\b",
        r"\bresign\b", r"\bjoin\b", r"\bleave\b", r"\bteam\b", r"\bwho\s+is\b",
    ],
    QueryIntent.TEMPORAL: [
        r"\bq[1-4]\b", r"\bquarter\b", r"\byear\b", r"\b20\d{2}\b",
        r"\blatest\b", r"\brecent\b", r"\bhistor\b", r"\btrend\b",
    ],
    QueryIntent.METRIC: [
        r"\baum\b", r"\bnav\b", r"\breturn\b", r"\byield\b",
        r"\bexpense ratio\b", r"\bperformance\b", r"\bgrowth\b",
        r"\balpha\b", r"\bbeta\b", r"\bsharpe\b",
    ],
    QueryIntent.SUMMARY: [
        r"\bsummar\b", r"\boverview\b", r"\bbr?ief\b", r"\bhighlight\b",
        r"\bdescribe\b", r"\bwhat is\b", r"\btell me about\b",
    ],
}


def classify_intent(query: str) -> QueryIntent:
    q = query.lower()
    scores = {intent: 0 for intent in QueryIntent}
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, q):
                scores[intent] += 1
    best = max(scores, key=lambda k: scores[k])
    return QueryIntent.GENERAL if scores[best] == 0 else best


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def reciprocal_rank_fusion(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            wid = item["weaviate_id"]
            scores[wid] = scores.get(wid, 0.0) + 1.0 / (k + rank + 1)
            items[wid] = item
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    results = []
    for wid in sorted_ids:
        item = items[wid].copy()
        item["rrf_score"] = scores[wid]
        results.append(item)
    return results


# ── Re-ranking with score threshold ──────────────────────────────────────────

def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates:
        return []
    sorted_candidates = sorted(candidates, key=lambda x: x.get("rrf_score", 0), reverse=True)
    return sorted_candidates[:top_k]


# ── Citation builder — only cite docs that genuinely contributed ───────────────

def _build_citations(chunks: list[dict], score_threshold_pct: float = 0.80) -> list[dict]:
    """
    Build citations from chunks, but only include documents that have
    RRF scores above a relative threshold.

    score_threshold_pct = 0.5 means: only cite docs whose best chunk
    has a score >= 50% of the top chunk's score.

    This prevents listing all 3 documents when only 1 actually answered
    the question.
    """
    if not chunks:
        return []

    # Find the top score for relative thresholding
    top_score = max(c.get("rrf_score", 0) for c in chunks)
    min_score = top_score * score_threshold_pct

    # Group chunks by document, track best score per doc
    doc_best_score: dict[str, float] = {}
    doc_info: dict[str, dict] = {}

    for chunk in chunks:
        doc_id = chunk.get("document_id", "")
        score = chunk.get("rrf_score", 0)
        if doc_id not in doc_best_score or score > doc_best_score[doc_id]:
            doc_best_score[doc_id] = score
            # Store the best-scoring chunk's metadata for this doc
            doc_info[doc_id] = chunk

    # Only cite documents above the threshold
    qualifying_docs = [
        (doc_id, doc_best_score[doc_id])
        for doc_id in doc_best_score
        if doc_best_score[doc_id] >= min_score
    ]

    # Sort by score descending
    qualifying_docs.sort(key=lambda x: x[1], reverse=True)

    citations = []
    for ref_num, (doc_id, score) in enumerate(qualifying_docs, 1):
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

    logger.info(
        "Citations filtered",
        total_chunks=len(chunks),
        qualifying_docs=len(qualifying_docs),
        top_score=round(top_score, 4),
        min_score=round(min_score, 4),
    )

    return citations


def assemble_context(chunks: list[dict], max_tokens: int = 8000) -> tuple[str, list[dict]]:
    """Build context string + citation list from top chunks."""
    context_parts = []
    total_tokens = 0
    used_chunks = []

    for i, chunk in enumerate(chunks):
        chunk_tokens = chunk.get("token_count", 200)
        if total_tokens + chunk_tokens > max_tokens:
            break
        doc_header = (
            f"[{i+1}] {chunk.get('filename', 'Unknown')} "
            f"| Page {chunk.get('page_start', '?')} "
            f"| {chunk.get('section_title') or chunk.get('doc_type', '')}"
        )
        context_parts.append(f"{doc_header}\n{chunk['content']}")
        total_tokens += chunk_tokens
        used_chunks.append(chunk)

    context = "\n\n---\n\n".join(context_parts)
    citations = _build_citations(used_chunks)
    return context, citations


# ── Main Retrieval Function ───────────────────────────────────────────────────

async def retrieve(
    query: str,
    tenant_id: str,
    doc_ids: Optional[list[str]] = None,
    doc_type_filter: Optional[str] = None,
    top_k_retrieve: int = None,
    top_k_rerank: int = None,
) -> RetrievalResult:
    top_k_retrieve = top_k_retrieve or settings.top_k_retrieve
    top_k_rerank = top_k_rerank or settings.top_k_rerank

    intent = classify_intent(query)
    logger.info("Query intent", intent=intent.value, query=query[:80])

    # Vector search
    query_vector = await embed_single(query)
    vector_results = semantic_search(
        query_vector=query_vector,
        tenant_id=tenant_id,
        doc_type_filter=doc_type_filter,
        doc_ids=doc_ids,
        top_k=top_k_retrieve,
    )

    # BM25 keyword search
    bm25_results = bm25_search(
        query=query,
        tenant_id=tenant_id,
        doc_type_filter=doc_type_filter,
        doc_ids=doc_ids,
        top_k=top_k_retrieve,
    )

    logger.info("Raw results", vector=len(vector_results), bm25=len(bm25_results))

    # RRF fusion + rerank
    fused = reciprocal_rank_fusion([vector_results, bm25_results])
    reranked = rerank(query, fused, top_k=top_k_rerank)

    # Context + citations (only relevant docs cited)
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
            rerank_score=c.get("rerank_score", 0.0),
        )
        for c in reranked
    ]

    return RetrievalResult(
        query=query,
        intent=intent,
        chunks=chunks,
        citations=citations,
        context_text=context_text,
        total_tokens=sum(c.get("token_count", 0) for c in reranked),
    )
