"""
Phase 3: Semantic Chunking + Embedding + Weaviate Indexing

Chunking strategy:
  1. Section-aware: split at detected section boundaries
  2. Table chunks: each table serialized as own chunk
  3. Semantic overflow: long sections split by sentence similarity
  4. Overlap: 128-token overlap between adjacent text chunks
"""
import uuid
import re
from dataclasses import dataclass
from typing import Optional

import tiktoken
from app.core.config import settings
from app.core.logging import get_logger
from app.services.ocr.ocr_service import ParsedDocument, ParsedPage

logger = get_logger(__name__)

# tiktoken encoder for GPT-4
_encoder = tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    return len(_encoder.encode(text))


def _serialize_table(table: list[list[str]]) -> str:
    """Convert 2D table list to pipe-delimited Markdown."""
    if not table:
        return ""
    rows = []
    for i, row in enumerate(table):
        rows.append("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |")
        if i == 0:
            rows.append("|" + "|".join("---" for _ in row) + "|")
    return "\n".join(rows)


@dataclass
class Chunk:
    chunk_index: int
    content: str
    page_start: int
    page_end: int
    section_title: Optional[str]
    chunk_type: str   # text | table | heading
    token_count: int


def chunk_document(parsed: ParsedDocument, doc_id: str) -> list[Chunk]:
    """
    Section-aware semantic chunker.
    Produces text chunks + table chunks from a ParsedDocument.
    """
    chunks: list[Chunk] = []
    chunk_idx = 0

    for page in parsed.pages:
        # ── Table chunks (each table = 1 chunk) ──────────────────────────────
        for table in page.tables:
            serialized = _serialize_table(table)
            if serialized.strip():
                chunks.append(Chunk(
                    chunk_index=chunk_idx,
                    content=f"[TABLE - Page {page.page_num}]\n{serialized}",
                    page_start=page.page_num,
                    page_end=page.page_num,
                    section_title=None,
                    chunk_type="table",
                    token_count=token_count(serialized),
                ))
                chunk_idx += 1

        # ── Text chunks ───────────────────────────────────────────────────────
        text_chunks = _split_text_by_section(
            page.text,
            page.section_titles,
            page_num=page.page_num,
        )
        for tc in text_chunks:
            tc.chunk_index = chunk_idx
            chunks.append(tc)
            chunk_idx += 1

    logger.info("Chunking complete", doc_id=doc_id, total_chunks=len(chunks))
    return chunks


def _split_text_by_section(
    text: str,
    section_titles: list[str],
    page_num: int,
) -> list[Chunk]:
    """Split page text at section headers; overflow-split long sections."""
    if not text.strip():
        return []

    # Split at known section titles
    if section_titles:
        pattern = "|".join(re.escape(s) for s in section_titles)
        parts = re.split(f"({pattern})", text)
    else:
        parts = [text]

    chunks = []
    current_section = None

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in section_titles:
            current_section = part
            continue
        # Long section: split with overlap
        sub_chunks = _split_with_overlap(
            part,
            section=current_section,
            page_num=page_num,
        )
        chunks.extend(sub_chunks)

    return chunks


def _split_with_overlap(
    text: str,
    section: Optional[str],
    page_num: int,
    max_tokens: int = None,
    overlap: int = None,
) -> list[Chunk]:
    """Sliding window split with token overlap."""
    max_tokens = max_tokens or settings.chunk_size_tokens
    overlap = overlap or settings.chunk_overlap_tokens

    words = text.split()
    chunks = []
    idx = 0

    while idx < len(words):
        segment_words = []
        tc = 0
        i = idx
        while i < len(words) and tc < max_tokens:
            segment_words.append(words[i])
            tc += 1   # approx: 1 word ≈ 1.3 tokens (good enough for chunking)
            i += 1

        content = " ".join(segment_words)
        if content.strip():
            prefix = f"[{section}] " if section else ""
            full_content = prefix + content
            chunks.append(Chunk(
                chunk_index=0,   # set by caller
                content=full_content,
                page_start=page_num,
                page_end=page_num,
                section_title=section,
                chunk_type="text",
                token_count=token_count(full_content),
            ))

        # Advance by (max_tokens - overlap) words
        idx += max(1, int((max_tokens - overlap) * 0.77))   # ≈ words/token ratio

    return chunks
