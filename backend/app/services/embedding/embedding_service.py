"""
Embedding Service — Multi-Provider
Supports: OpenAI | Azure OpenAI | Ollama | HuggingFace (local)

Set EMBEDDING_PROVIDER in .env to switch providers.
Default: huggingface (free, runs in container, no API key needed)
"""
import asyncio
import hashlib
import json
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

BATCH_SIZE = 50
MAX_RETRIES = 5
BASE_DELAY = 3.0

# ── HuggingFace local model (loaded once, reused) ─────────────────────────────
_hf_model = None

def _get_hf_model():
    global _hf_model
    if _hf_model is None:
        from sentence_transformers import SentenceTransformer
        model_name = settings.hf_embedding_model
        logger.info("Loading HuggingFace embedding model", model=model_name)
        _hf_model = SentenceTransformer(model_name)
        logger.info("HuggingFace model loaded", model=model_name)
    return _hf_model


# ── Provider implementations ──────────────────────────────────────────────────

async def _embed_huggingface(texts: list[str]) -> list[list[float]]:
    """Free local embeddings via sentence-transformers. No API key needed."""
    loop = asyncio.get_event_loop()
    model = _get_hf_model()
    embeddings = await loop.run_in_executor(
        None,
        lambda: model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    )
    return embeddings.tolist()


async def _embed_ollama(texts: list[str]) -> list[list[float]]:
    """Free local embeddings via Ollama (nomic-embed-text)."""
    import httpx
    model = settings.ollama_embedding_model
    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for text in texts:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            resp.raise_for_status()
            results.append(resp.json()["embedding"])
    return results


async def _embed_openai(texts: list[str]) -> list[list[float]]:
    """OpenAI embeddings (paid, requires API key)."""
    from openai import AsyncOpenAI, RateLimitError
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.embeddings.create(
                model=settings.openai_embedding_model,
                input=texts,
            )
            return [item.embedding for item in resp.data]
        except RateLimitError:
            delay = BASE_DELAY * (2 ** attempt)
            logger.warning("OpenAI rate limit, retrying", attempt=attempt, delay=delay)
            await asyncio.sleep(delay)
        except Exception as exc:
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(BASE_DELAY * (2 ** attempt))
    raise RuntimeError("OpenAI embedding failed after max retries")


async def _embed_azure(texts: list[str]) -> list[list[float]]:
    """Azure OpenAI embeddings (paid, requires Azure key)."""
    from openai import AsyncAzureOpenAI
    client = AsyncAzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    resp = await client.embeddings.create(
        model=settings.azure_openai_embedding_deployment,
        input=texts,
    )
    return [item.embedding for item in resp.data]


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Route to correct provider based on EMBEDDING_PROVIDER setting."""
    provider = settings.embedding_provider.lower()
    logger.info("Embedding batch", provider=provider, count=len(texts))

    if provider in ("huggingface", "local"):
        return await _embed_huggingface(texts)
    elif provider == "ollama":
        return await _embed_ollama(texts)
    elif provider == "azure":
        return await _embed_azure(texts)
    elif provider == "openai":
        return await _embed_openai(texts)
    else:
        logger.warning("Unknown embedding provider, falling back to HuggingFace", provider=provider)
        return await _embed_huggingface(texts)


# ── Public API ────────────────────────────────────────────────────────────────

def _cache_key(text: str, model: str) -> str:
    return f"embed:{hashlib.md5(f'{model}:{text}'.encode()).hexdigest()}"


async def embed_texts(texts: list[str], use_cache: bool = True) -> list[list[float]]:
    if not texts:
        return []

    results: list[Optional[list[float]]] = [None] * len(texts)
    uncached = list(range(len(texts)))

    # Redis cache lookup
    if use_cache:
        try:
            import redis.asyncio as aioredis
            r = await aioredis.from_url(settings.redis_url, decode_responses=False)
            model_key = settings.embedding_provider + ":" + settings.hf_embedding_model
            cached_vals = await r.mget([_cache_key(texts[i], model_key) for i in uncached])
            still_uncached = []
            for pos, val in enumerate(cached_vals):
                if val is not None:
                    results[pos] = json.loads(val)
                else:
                    still_uncached.append(pos)
            uncached = still_uncached
            await r.aclose()
        except Exception:
            pass

    if not uncached:
        return results  # type: ignore

    # Embed in batches
    uncached_texts = [texts[i] for i in uncached]
    all_embeddings: list[list[float]] = []

    for batch_num, start in enumerate(range(0, len(uncached_texts), BATCH_SIZE)):
        batch = uncached_texts[start:start + BATCH_SIZE]
        embs = await _embed_batch(batch)
        all_embeddings.extend(embs)
        if batch_num > 0:
            await asyncio.sleep(0.5)  # small pause between batches

    for pos, orig_idx in enumerate(uncached):
        results[orig_idx] = all_embeddings[pos]

    # Cache results
    if use_cache:
        try:
            import redis.asyncio as aioredis
            r = await aioredis.from_url(settings.redis_url, decode_responses=False)
            model_key = settings.embedding_provider + ":" + settings.hf_embedding_model
            pipe = r.pipeline()
            for pos, orig_idx in enumerate(uncached):
                pipe.setex(_cache_key(texts[orig_idx], model_key), 86400, json.dumps(all_embeddings[pos]))
            await pipe.execute()
            await r.aclose()
        except Exception:
            pass

    return results  # type: ignore


async def embed_single(text: str) -> list[float]:
    result = await embed_texts([text])
    return result[0]
