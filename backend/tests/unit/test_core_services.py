"""
Unit tests for core services:
  - Chunker (section-aware, table serializer, overlap)
  - Retrieval engine (intent classifier, RRF fusion)
  - Ingestion service (dedup, validation)
  - Audit service (HMAC chain)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


# ── Chunker ───────────────────────────────────────────────────────────────────

class TestChunker:
    """Tests for app.services.embedding.chunker"""

    def _make_parsed(self, text: str, tables=None, sections=None):
        from app.services.ocr.ocr_service import ParsedDocument, ParsedPage
        page = ParsedPage(
            page_num=1,
            text=text,
            tables=tables or [],
            section_titles=sections or [],
            is_ocr=False,
        )
        return ParsedDocument(
            pages=[page],
            page_count=1,
            is_scanned=False,
            avg_ocr_confidence=None,
            detected_language="en",
            fund_name=None,
            report_date=None,
            entities={},
            full_text=text,
        )

    def test_basic_text_produces_chunks(self):
        from app.services.embedding.chunker import chunk_document
        text = "This is a test paragraph with some financial content. " * 20
        parsed = self._make_parsed(text)
        chunks = chunk_document(parsed, "doc-001")
        assert len(chunks) > 0
        assert all(c.content for c in chunks)
        assert all(c.token_count > 0 for c in chunks)

    def test_table_chunk_type(self):
        from app.services.embedding.chunker import chunk_document
        table = [["Fund", "AUM", "NAV"], ["ABC Fund", "$4.2B", "$105.3"]]
        parsed = self._make_parsed("Some text before the table.", tables=[table])
        chunks = chunk_document(parsed, "doc-002")
        table_chunks = [c for c in chunks if c.chunk_type == "table"]
        assert len(table_chunks) == 1
        assert "ABC Fund" in table_chunks[0].content
        assert "---" in table_chunks[0].content  # Markdown separator

    def test_section_aware_splitting(self):
        from app.services.embedding.chunker import chunk_document
        text = "INVESTMENT STRATEGY\nWe invest in equities globally.\n\nRISK FACTORS\nMarket risk applies."
        parsed = self._make_parsed(text, sections=["INVESTMENT STRATEGY", "RISK FACTORS"])
        chunks = chunk_document(parsed, "doc-003")
        assert len(chunks) >= 2

    def test_empty_document(self):
        from app.services.embedding.chunker import chunk_document
        parsed = self._make_parsed("")
        chunks = chunk_document(parsed, "doc-004")
        assert chunks == []

    def test_table_serializer(self):
        from app.services.embedding.chunker import _serialize_table
        table = [["Fund", "AUM"], ["ABC", "$4.2B"], ["XYZ", "$1.1B"]]
        result = _serialize_table(table)
        assert "Fund" in result
        assert "---" in result
        assert "$4.2B" in result
        assert "|" in result


# ── Intent Classifier ─────────────────────────────────────────────────────────

class TestIntentClassifier:
    """Tests for retrieval_engine.classify_intent"""

    def test_summary_intent(self):
        from app.services.retrieval.retrieval_engine import classify_intent, QueryIntent
        assert classify_intent("summarize the ABC fund") == QueryIntent.SUMMARY
        assert classify_intent("give me an overview of the portfolio") == QueryIntent.SUMMARY

    def test_comparison_intent(self):
        from app.services.retrieval.retrieval_engine import classify_intent, QueryIntent
        assert classify_intent("compare ABC fund vs XYZ fund") == QueryIntent.COMPARISON
        assert classify_intent("what is the difference between these two funds") == QueryIntent.COMPARISON

    def test_personnel_intent(self):
        from app.services.retrieval.retrieval_engine import classify_intent, QueryIntent
        assert classify_intent("any personnel changes in Q3?") == QueryIntent.PERSONNEL
        assert classify_intent("who is the fund manager") == QueryIntent.PERSONNEL

    def test_temporal_intent(self):
        from app.services.retrieval.retrieval_engine import classify_intent, QueryIntent
        assert classify_intent("what happened in Q3 2025") == QueryIntent.TEMPORAL
        assert classify_intent("show me the latest quarterly results") == QueryIntent.TEMPORAL

    def test_metric_intent(self):
        from app.services.retrieval.retrieval_engine import classify_intent, QueryIntent
        assert classify_intent("what is the AUM of the fund?") == QueryIntent.METRIC
        assert classify_intent("show me the NAV and expense ratio") == QueryIntent.METRIC

    def test_general_fallback(self):
        from app.services.retrieval.retrieval_engine import classify_intent, QueryIntent
        assert classify_intent("hello there") == QueryIntent.GENERAL


# ── Reciprocal Rank Fusion ─────────────────────────────────────────────────────

class TestRRF:
    """Tests for retrieval_engine.reciprocal_rank_fusion"""

    def _make_result(self, wid: str, score: float = 0.9):
        return {"weaviate_id": wid, "content": f"Content {wid}", "score": score, "token_count": 50}

    def test_deduplication(self):
        from app.services.retrieval.retrieval_engine import reciprocal_rank_fusion
        list1 = [self._make_result("a"), self._make_result("b"), self._make_result("c")]
        list2 = [self._make_result("b"), self._make_result("a"), self._make_result("d")]
        result = reciprocal_rank_fusion([list1, list2])
        ids = [r["weaviate_id"] for r in result]
        assert len(ids) == len(set(ids))  # no duplicates

    def test_top_items_boosted(self):
        from app.services.retrieval.retrieval_engine import reciprocal_rank_fusion
        # "a" appears first in both lists → should have highest RRF score
        list1 = [self._make_result("a"), self._make_result("b")]
        list2 = [self._make_result("a"), self._make_result("c")]
        result = reciprocal_rank_fusion([list1, list2])
        assert result[0]["weaviate_id"] == "a"

    def test_empty_lists(self):
        from app.services.retrieval.retrieval_engine import reciprocal_rank_fusion
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[]]) == []


# ── Ingestion Service ─────────────────────────────────────────────────────────

class TestIngestionService:
    """Tests for ingestion_service"""

    def test_classify_doc_type_fact_sheet(self):
        from app.services.ingestion.ingestion_service import IngestionService
        from app.models.models import DocumentType
        svc = IngestionService()
        assert svc._classify_doc_type("ABC_Factsheet_Q3.pdf", {}) == DocumentType.FACT_SHEET

    def test_classify_doc_type_quarterly(self):
        from app.services.ingestion.ingestion_service import IngestionService
        from app.models.models import DocumentType
        svc = IngestionService()
        assert svc._classify_doc_type("Q3_2025_Report.pdf", {}) == DocumentType.QUARTERLY_REPORT

    def test_classify_doc_type_personnel(self):
        from app.services.ingestion.ingestion_service import IngestionService
        from app.models.models import DocumentType
        svc = IngestionService()
        assert svc._classify_doc_type("personnel_notice_march25.pdf", {}) == DocumentType.PERSONNEL

    def test_sha256_consistency(self):
        from app.services.ingestion.ingestion_service import IngestionService
        svc = IngestionService()
        data = b"test pdf content"
        assert svc._compute_sha256(data) == svc._compute_sha256(data)
        assert svc._compute_sha256(data) != svc._compute_sha256(b"different")

    def test_sha256_length(self):
        from app.services.ingestion.ingestion_service import IngestionService
        svc = IngestionService()
        h = svc._compute_sha256(b"content")
        assert len(h) == 64  # SHA-256 hex = 64 chars


# ── OCR Service ───────────────────────────────────────────────────────────────

class TestOCRService:
    """Tests for ocr_service metadata extraction"""

    def test_extract_fund_name(self):
        from app.services.ocr.ocr_service import _extract_fund_name
        text = "ABC Growth Fund Fact Sheet — Q3 2025\nTotal Assets: $4.2B"
        result = _extract_fund_name(text)
        assert result is not None
        assert "ABC" in result

    def test_extract_report_date_quarter(self):
        from app.services.ocr.ocr_service import _extract_report_date
        text = "As of Q3 2025\nFund Performance Report"
        result = _extract_report_date(text)
        assert result is not None
        assert "Q3" in result

    def test_extract_report_date_full(self):
        from app.services.ocr.ocr_service import _extract_report_date
        text = "Report Date: September 30, 2025"
        result = _extract_report_date(text)
        assert result is not None

    def test_extract_section_titles(self):
        from app.services.ocr.ocr_service import _detect_sections
        text = "INVESTMENT STRATEGY\nWe invest in global equities.\n\nRISK FACTORS\nMarket risk."
        sections = _detect_sections(text)
        assert "INVESTMENT STRATEGY" in sections or "RISK FACTORS" in sections


# ── Audit HMAC Chain ──────────────────────────────────────────────────────────

class TestAuditHMAC:
    """Tests for audit_service HMAC chain"""

    def test_hmac_deterministic(self):
        from app.services.audit_service import _compute_hmac
        record = {"action": "upload", "tenant_id": "abc", "timestamp": "2025-01-01"}
        h1 = _compute_hmac("genesis", record)
        h2 = _compute_hmac("genesis", record)
        assert h1 == h2

    def test_hmac_changes_with_prev(self):
        from app.services.audit_service import _compute_hmac
        record = {"action": "upload", "tenant_id": "abc", "timestamp": "2025-01-01"}
        h1 = _compute_hmac("genesis", record)
        h2 = _compute_hmac("different-prev", record)
        assert h1 != h2

    def test_hmac_changes_with_record(self):
        from app.services.audit_service import _compute_hmac
        r1 = {"action": "upload", "tenant_id": "abc", "timestamp": "2025-01-01"}
        r2 = {"action": "delete", "tenant_id": "abc", "timestamp": "2025-01-01"}
        assert _compute_hmac("genesis", r1) != _compute_hmac("genesis", r2)

    def test_hmac_length(self):
        from app.services.audit_service import _compute_hmac
        h = _compute_hmac("genesis", {"key": "value"})
        assert len(h) == 64  # SHA-256 hex


# ── Embedding Service ─────────────────────────────────────────────────────────

class TestEmbeddingService:
    """Tests for embedding_service (mocked OpenAI calls)"""

    @pytest.mark.asyncio
    async def test_embed_empty_returns_empty(self):
        from app.services.embedding.embedding_service import embed_texts
        with patch('app.services.embedding.embedding_service._get_redis') as mock_redis:
            mock_redis.return_value = AsyncMock()
            result = await embed_texts([])
            assert result == []

    def test_cache_key_consistent(self):
        from app.services.embedding.embedding_service import _cache_key
        k1 = _cache_key("hello world", "model-a")
        k2 = _cache_key("hello world", "model-a")
        k3 = _cache_key("hello world", "model-b")
        assert k1 == k2
        assert k1 != k3
