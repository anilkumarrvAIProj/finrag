"""
Fund Service
============
Manages fund-level Weaviate collections for namespace isolation.

Each fund gets its own Weaviate collection:
  Fund_<tenant_hex>_<fund_slug>

This ensures queries for Fund A NEVER retrieve Fund B chunks.
"""
import uuid
from typing import Optional

import weaviate
import weaviate.classes as wvc
from weaviate.classes.config import Configure, Property, DataType, Tokenization

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SHARED_COLLECTION = "FinragChunk"   # legacy — kept for backward compat


def _get_client() -> weaviate.WeaviateClient:
    url = settings.weaviate_url
    host = url.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(url.split(":")[-1]) if ":" in url.split("//")[-1] else 8080
    return weaviate.connect_to_local(host=host, port=port)


def _chunk_properties():
    """Standard properties for any fund chunk collection."""
    return [
        Property(name="tenant_id",     data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="fund_id",       data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="document_id",   data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="chunk_id",      data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="content",       data_type=DataType.TEXT, tokenization=Tokenization.WORD),
        Property(name="chunk_type",    data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="section_title", data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="page_start",    data_type=DataType.INT,  skip_vectorization=True),
        Property(name="page_end",      data_type=DataType.INT,  skip_vectorization=True),
        Property(name="doc_type",      data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="fund_name",     data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="report_date",   data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="filename",      data_type=DataType.TEXT, skip_vectorization=True),
        Property(name="token_count",   data_type=DataType.INT,  skip_vectorization=True),
        Property(name="namespace",     data_type=DataType.TEXT, skip_vectorization=True),
    ]


async def ensure_fund_weaviate_collection(collection_name: str) -> bool:
    """
    Create a Weaviate collection for a fund if it doesn't exist.
    Returns True if created, False if already existed.
    """
    try:
        with _get_client() as client:
            if client.collections.exists(collection_name):
                return False
            client.collections.create(
                name=collection_name,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=_chunk_properties(),
            )
            logger.info("Fund Weaviate collection created", collection=collection_name)
            return True
    except Exception as exc:
        logger.warning("Failed to create fund collection", collection=collection_name, error=str(exc))
        return False


def get_collection_for_fund(fund_weaviate_collection: Optional[str]) -> str:
    """Return the collection name to use — fund-specific or shared fallback."""
    return fund_weaviate_collection or SHARED_COLLECTION


def upsert_fund_chunks(
    chunks: list[dict],
    embeddings: list[list[float]],
    collection_name: str,
) -> list[str]:
    """Insert chunks into a fund-specific Weaviate collection."""
    weaviate_ids: list[str] = []
    with _get_client() as client:
        # Ensure collection exists
        if not client.collections.exists(collection_name):
            client.collections.create(
                name=collection_name,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=_chunk_properties(),
            )

        collection = client.collections.get(collection_name)
        with collection.batch.dynamic() as batch:
            for chunk, embedding in zip(chunks, embeddings):
                wid = str(uuid.uuid4())
                batch.add_object(properties=chunk, vector=embedding, uuid=wid)
                weaviate_ids.append(wid)
    return weaviate_ids


def semantic_search_fund(
    query_vector: list[float],
    collection_name: str,
    top_k: int = 20,
) -> list[dict]:
    """Vector search within a specific fund collection — no cross-fund leakage."""
    try:
        from weaviate.classes.query import MetadataQuery
        with _get_client() as client:
            if not client.collections.exists(collection_name):
                return []
            collection = client.collections.get(collection_name)
            result = collection.query.near_vector(
                near_vector=query_vector,
                limit=top_k,
                return_metadata=MetadataQuery(distance=True),
            )
            chunks = []
            for obj in result.objects:
                chunk = dict(obj.properties)
                chunk["weaviate_id"] = str(obj.uuid)
                chunk["score"] = 1 - (obj.metadata.distance or 0)
                chunks.append(chunk)
            return chunks
    except Exception as exc:
        logger.warning("Fund semantic search failed", collection=collection_name, error=str(exc))
        return []


def bm25_search_fund(
    query: str,
    collection_name: str,
    top_k: int = 20,
) -> list[dict]:
    """BM25 search within a specific fund collection."""
    try:
        from weaviate.classes.query import MetadataQuery
        with _get_client() as client:
            if not client.collections.exists(collection_name):
                return []
            collection = client.collections.get(collection_name)
            result = collection.query.bm25(
                query=query,
                query_properties=["content"],
                limit=top_k,
                return_metadata=MetadataQuery(score=True),
            )
            chunks = []
            for obj in result.objects:
                chunk = dict(obj.properties)
                chunk["weaviate_id"] = str(obj.uuid)
                chunk["bm25_score"] = obj.metadata.score or 0.0
                chunks.append(chunk)
            return chunks
    except Exception as exc:
        logger.warning("Fund BM25 search failed", collection=collection_name, error=str(exc))
        return []


def delete_fund_chunks(document_id: str, collection_name: str) -> int:
    """Delete all chunks for a document from its fund collection."""
    try:
        with _get_client() as client:
            if not client.collections.exists(collection_name):
                return 0
            collection = client.collections.get(collection_name)
            result = collection.data.delete_many(
                where=wvc.query.Filter.by_property("document_id").equal(document_id)
            )
            return result.successful if result else 0
    except Exception as exc:
        logger.warning("Fund chunk deletion failed", collection=collection_name, error=str(exc))
        return 0
