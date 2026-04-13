"""
Chat Orchestrator — Multi-Provider LLM
Supports: OpenAI | Azure OpenAI | Ollama (free local)

Set LLM_PROVIDER in .env to switch providers.
Default: ollama (free, runs locally)
"""
import json
import time
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.retrieval.retrieval_engine import QueryIntent, RetrievalResult, retrieve
from app.services.chat.response_formatter import enforce_table_format, is_tabular_query, clean_preamble, apply_response_title, strip_inline_sources

logger = get_logger(__name__)

BASE_SYSTEM = """You are FinRAG, an AI assistant for financial document analysis.

CRITICAL RULES:
1. Answer ONLY using the provided context. Do not use prior knowledge.
2. If the answer is not in the context, say exactly: "I could not find this information in the available documents."
3. Never fabricate numbers, dates, fund names, or personnel names.
4. If context chunks contradict each other, surface BOTH answers with their sources.

FORMATTING RULES (FOLLOW EXACTLY):
- NEVER start with "Based on", "Here are", "According to" or any preamble. Start directly with the answer.
- ANY query about returns, performance, fees, AUM, positions, investors, comparisons -> use a Markdown table.
- Table format: | Column | Column | then |---|---| row then data rows.
- Sources at the very bottom after --- separator line only, never inline.
- Example response for investor counts:
  | Fund | Investors |
  |------|-----------|
  | Aether Global Macro | 84 |
- For qualitative answers: start directly with content, no preamble.
"""


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_messages(query: str, result: RetrievalResult, web_context: Optional[str], history: list[dict]) -> list[dict]:
    parts = ["=== DOCUMENT CONTEXT ===", result.context_text or "No relevant documents found."]
    if web_context:
        parts += ["\n=== WEB SEARCH RESULTS ===", web_context]
    if history:
        parts.append("\n=== CONVERSATION HISTORY ===")
        for msg in history[-6:]:
            parts.append(f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content'][:400]}")
    parts.append(f"\n=== CURRENT QUESTION ===\n{query}")

    return [
        {"role": "system", "content": BASE_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


# ── Provider streaming implementations ───────────────────────────────────────

async def _stream_openai(messages: list[dict]) -> AsyncGenerator[str, None]:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    llm = ChatOpenAI(
        model=settings.openai_chat_model,
        temperature=0.0,
        streaming=True,
        api_key=settings.openai_api_key,
        max_tokens=2048,
    )
    lc_messages = [
        SystemMessage(content=messages[0]["content"]),
        HumanMessage(content=messages[1]["content"]),
    ]
    async for chunk in llm.astream(lc_messages):
        if chunk.content:
            yield chunk.content


async def _stream_azure(messages: list[dict]) -> AsyncGenerator[str, None]:
    from langchain_openai import AzureChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    llm = AzureChatOpenAI(
        azure_deployment=settings.azure_openai_chat_deployment,
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        temperature=0.0,
        streaming=True,
        max_tokens=2048,
    )
    lc_messages = [
        SystemMessage(content=messages[0]["content"]),
        HumanMessage(content=messages[1]["content"]),
    ]
    async for chunk in llm.astream(lc_messages):
        if chunk.content:
            yield chunk.content


async def _stream_ollama(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream from local Ollama. Tries /api/chat first, falls back to /api/generate."""
    import httpx

    # Build combined prompt for /api/generate fallback
    combined_prompt = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    ) + "\nASSISTANT:"

    async with httpx.AsyncClient(timeout=300) as client:
        # Try /api/chat first (Ollama >= 0.1.14)
        try:
            payload = {
                "model": settings.ollama_chat_model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": 0.0},
            }
            async with client.stream("POST", f"{settings.ollama_base_url}/api/chat", json=payload) as resp:
                if resp.status_code == 404:
                    raise Exception("endpoint not found")
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            token = data.get("message", {}).get("content", "")
                            if token:
                                yield token
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
            return
        except Exception:
            pass  # fall through to /api/generate

        # Fallback: /api/generate (older Ollama)
        payload = {
            "model": settings.ollama_chat_model,
            "prompt": combined_prompt,
            "stream": True,
            "options": {"temperature": 0.0},
        }
        async with client.stream("POST", f"{settings.ollama_base_url}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    try:
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            yield token
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue


async def web_search(query: str) -> tuple[str, list[dict]]:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(query=query, max_results=5)
        sources, parts = [], []
        for i, r in enumerate(resp.get("results", []), 1):
            sources.append({"ref": i, "title": r.get("title", ""), "url": r.get("url", "")})
            parts.append(f"[WEB-{i}] {r.get('title','')} ({r.get('url','')})\n{r.get('content','')[:800]}")
        return "\n\n".join(parts), sources
    except Exception as exc:
        logger.warning("Web search failed", error=str(exc))
        return "", []


async def chat_stream(
    query: str,
    tenant_id: str,
    history: list[dict],
    doc_ids: Optional[list[str]] = None,
    doc_type_filter: Optional[str] = None,
    fund_collection: Optional[str] = None,
    enable_web_search: bool = False,
    output_format: str = "paragraph",
) -> AsyncGenerator[str, None]:

    start_time = time.time()
    provider = settings.llm_provider.lower()

    yield _sse("status", {"message": "Searching documents..."})

    try:
        result = await retrieve(
            query=query, tenant_id=tenant_id,
            doc_ids=doc_ids, doc_type_filter=doc_type_filter,
            fund_collection=fund_collection,
        )
    except Exception as exc:
        logger.error("Retrieval failed", error=str(exc))
        yield _sse("error", {"message": f"Retrieval failed: {str(exc)}"})
        return

    yield _sse("retrieval_complete", {
        "chunks_found": len(result.chunks),
        "intent": result.intent.value,
        "citations": result.citations,
    })

    web_context, web_sources = None, []
    if enable_web_search and settings.tavily_api_key:
        yield _sse("status", {"message": "Searching the web..."})
        web_context, web_sources = await web_search(query)

    messages = _build_messages(query, result, web_context, history)

    yield _sse("status", {"message": f"Generating response ({provider})..."})

    full_response = ""
    try:
        if provider == "openai":
            stream_fn = _stream_openai(messages)
        elif provider == "azure":
            stream_fn = _stream_azure(messages)
        elif provider == "ollama":
            stream_fn = _stream_ollama(messages)
        else:
            logger.warning("Unknown LLM provider, falling back to Ollama", provider=provider)
            stream_fn = _stream_ollama(messages)

        async for token in stream_fn:
            full_response += token
            yield _sse("token", {"text": token})

    except Exception as exc:
        logger.error("LLM streaming error", error=str(exc), provider=provider)
        # Return a helpful error message in the stream
        error_msg = f"\n\n⚠️ LLM provider '{provider}' failed: {str(exc)}\n\nPlease check:\n"
        if provider == "ollama":
            error_msg += "- Is Ollama running? Add the ollama service to docker-compose.yml\n- Or switch LLM_PROVIDER=openai in .env"
        elif provider == "openai":
            error_msg += "- Check OPENAI_API_KEY in .env\n- Or switch LLM_PROVIDER=ollama for free local inference"
        yield _sse("token", {"text": error_msg})
        full_response = error_msg

    latency_ms = int((time.time() - start_time) * 1000)
    # Post-process pipeline
    full_response = clean_preamble(full_response)
    full_response = strip_inline_sources(full_response)
    full_response = enforce_table_format(full_response, query)
    full_response = apply_response_title(full_response, query)
    yield _sse("done", {
        "citations": result.citations,
        "web_sources": web_sources,
        "web_search_used": bool(web_context),
        "latency_ms": latency_ms,
        "full_response": full_response,
        "intent": result.intent.value,
        "provider": provider,
    })
    logger.info("Chat complete", provider=provider, latency_ms=latency_ms)
