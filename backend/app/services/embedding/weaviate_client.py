"""Weaviate Vector Store Client."""
import uuid
from typing import Optional

import weaviate
from weaviate.classes.config import Configure, Property, DataType, Tokenization
from weaviate.classes.query import MetadataQuery
import weaviate.classes as wvc

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
WEAVIATE_CLASS = "FinragChunk"


def _get_client() -> weaviate.WeaviateClient:
    url = settings.weaviate_url  # e.g. http://weaviate:8080
    host = url.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(url.split(":")[-1]) if ":" in url.split("//")[-1] else 8080
    return weaviate.connect_to_local(host=host, port=port)


def ensure_schema() -> None:
    try:
        with _get_client() as client:
            if client.collections.exists(WEAVIATE_CLASS):
                logger.info("Weaviate schema exists")
                return
            client.collections.create(
                name=WEAVIATE_CLASS,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="tenant_id",     data_type=DataType.TEXT, skip_vectorization=True),
                    Property(name="namespace",     data_type=DataType.TEXT, skip_vectorization=True),
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
                ],
            )
            logger.info("Weaviate schema created")
    except Exception as exc:
        logger.warning("Weaviate schema setup failed", error=str(exc))
        raise


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]]) -> list[str]:
    weaviate_ids: list[str] = []
    with _get_client() as client:
        collection = client.collections.get(WEAVIATE_CLASS)
        with collection.batch.dynamic() as batch:
            for chunk, embedding in zip(chunks, embeddings):
                wid = str(uuid.uuid4())
                batch.add_object(properties=chunk, vector=embedding, uuid=wid)
                weaviate_ids.append(wid)
    return weaviate_ids


def delete_by_document(document_id: str, tenant_id: str) -> int:
    with _get_client() as client:
        collection = client.collections.get(WEAVIATE_CLASS)
        result = collection.data.delete_many(
            where=wvc.query.Filter.by_property("document_id").equal(document_id)
        )
        return result.successful if result else 0


def semantic_search(query_vector, tenant_id, doc_type_filter=None, doc_ids=None, top_k=20) -> list[dict]:
    try:
        with _get_client() as client:
            collection = client.collections.get(WEAVIATE_CLASS)
            filters = wvc.query.Filter.by_property("tenant_id").equal(tenant_id)
            if doc_type_filter:
                filters = filters & wvc.query.Filter.by_property("doc_type").equal(doc_type_filter)
            result = collection.query.near_vector(
                near_vector=query_vector, limit=top_k, filters=filters,
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
        logger.warning("Semantic search failed", error=str(exc))
        return []


def bm25_search(query, tenant_id, doc_type_filter=None, doc_ids=None, top_k=20) -> list[dict]:
    try:
        with _get_client() as client:
            collection = client.collections.get(WEAVIATE_CLASS)
            filters = wvc.query.Filter.by_property("tenant_id").equal(tenant_id)
            result = collection.query.bm25(
                query=query, query_properties=["content"], limit=top_k, filters=filters,
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
        logger.warning("BM25 search failed", error=str(exc))
        return []
