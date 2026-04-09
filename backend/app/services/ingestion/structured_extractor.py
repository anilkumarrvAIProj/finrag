"""
Structured Data Extractor
Uses LLM to extract structured financial data from document text
and stores it in PostgreSQL for precise retrieval.
"""
import json
import uuid
import re
from datetime import date
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

EXTRACTION_PROMPT = """You are a financial data extraction specialist.
Extract structured data from the following financial document text.

Return ONLY a valid JSON object with this exact structure (use null for missing fields):
{
  "fund_name": "string or null",
  "manager_name": "string or null",
  "strategy": "string or null - e.g. Long/Short Equity, Global Macro, Credit",
  "report_date": "YYYY-MM-DD or null",
  "period": "string or null - e.g. Q1 2025, January 2025",
  "aum_usd": number_in_millions_or_null,
  "aum_raw": "string or null - e.g. $4.2B",
  "return_mtd": number_percent_or_null,
  "return_qtd": number_percent_or_null,
  "return_ytd": number_percent_or_null,
  "return_1yr": number_percent_or_null,
  "return_3yr": number_percent_or_null,
  "return_inception": number_percent_or_null,
  "volatility": number_percent_or_null,
  "sharpe_ratio": number_or_null,
  "max_drawdown": number_percent_or_null,
  "beta": number_or_null,
  "management_fee": number_percent_or_null,
  "performance_fee": number_percent_or_null,
  "liquidity_terms": "string or null",
  "redemption_notice": "string or null",
  "benchmark_name": "string or null",
  "top_positions": [
    {"name": "string", "weight_pct": number_or_null, "direction": "long/short/null", "rank": 1}
  ],
  "personnel_changes": [
    {"name": "string", "previous_role": "string or null", "new_role": "string or null",
     "change_type": "joined/left/promoted", "effective_date": "YYYY-MM-DD or null"}
  ]
}

Return ONLY the JSON, no explanation, no markdown code blocks.

Document text:
"""


async def extract_structured_data(text: str, doc_id: str) -> Optional[dict]:
    """Extract structured financial data using LLM."""
    from app.core.config import settings

    # Use first 4000 chars — enough for key metrics
    sample = text[:4000]

    try:
        if settings.llm_provider.lower() == "ollama":
            result = await _extract_ollama(sample, settings)
        elif settings.llm_provider.lower() == "openai":
            result = await _extract_openai(sample, settings)
        elif settings.llm_provider.lower() == "azure":
            result = await _extract_azure(sample, settings)
        else:
            result = await _extract_ollama(sample, settings)

        if result:
            logger.info("Structured extraction complete", doc_id=doc_id,
                        fund=result.get("fund_name"), fields=len([v for v in result.values() if v is not None]))
        return result

    except Exception as exc:
        logger.warning("Structured extraction failed", doc_id=doc_id, error=str(exc))
        return None


async def _extract_ollama(text: str, settings) -> Optional[dict]:
    import httpx
    payload = {
        "model": settings.ollama_chat_model,
        "messages": [
            {"role": "user", "content": EXTRACTION_PROMPT + text}
        ],
        "stream": False,
        "options": {"temperature": 0.0},
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _parse_json(content)


async def _extract_openai(text: str, settings) -> Optional[dict]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT + text}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)


async def _extract_azure(text: str, settings) -> Optional[dict]:
    from openai import AsyncAzureOpenAI
    client = AsyncAzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    resp = await client.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT + text}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)


def _parse_json(content: str) -> Optional[dict]:
    try:
        content = content.strip()
        # Strip markdown code blocks if present
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        return json.loads(content)
    except Exception as exc:
        logger.warning("JSON parse failed", error=str(exc), content=content[:200])
        return None


async def save_structured_data(
    extracted: dict,
    doc_id: str,
    tenant_id: str,
    db,  # SQLAlchemy async session
) -> Optional[str]:
    """Save extracted structured data to PostgreSQL. Returns fund_id."""
    from app.models.structured_data import Fund, FundSnapshot, FundPosition, PersonnelChange
    from sqlalchemy import select

    if not extracted or not extracted.get("fund_name"):
        return None

    tenant_uuid = uuid.UUID(tenant_id)
    doc_uuid = uuid.UUID(doc_id)

    # Get or create fund
    fund_name = extracted["fund_name"]
    result = await db.execute(
        select(Fund).where(Fund.fund_name == fund_name, Fund.tenant_id == tenant_uuid)
    )
    fund = result.scalar_one_or_none()

    if not fund:
        fund = Fund(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            fund_name=fund_name,
            manager_name=extracted.get("manager_name"),
            strategy=extracted.get("strategy"),
        )
        db.add(fund)
        await db.flush()
        logger.info("New fund created", fund_name=fund_name)

    # Parse report date
    report_date = None
    if extracted.get("report_date"):
        try:
            from datetime import datetime
            report_date = datetime.strptime(extracted["report_date"], "%Y-%m-%d").date()
        except Exception:
            pass

    # Save snapshot
    snapshot = FundSnapshot(
        id=uuid.uuid4(),
        fund_id=fund.id,
        tenant_id=tenant_uuid,
        document_id=doc_uuid,
        report_date=report_date,
        period=extracted.get("period"),
        aum_usd=extracted.get("aum_usd"),
        aum_raw=extracted.get("aum_raw"),
        return_mtd=extracted.get("return_mtd"),
        return_qtd=extracted.get("return_qtd"),
        return_ytd=extracted.get("return_ytd"),
        return_1yr=extracted.get("return_1yr"),
        return_3yr=extracted.get("return_3yr"),
        return_inception=extracted.get("return_inception"),
        volatility=extracted.get("volatility"),
        sharpe_ratio=extracted.get("sharpe_ratio"),
        max_drawdown=extracted.get("max_drawdown"),
        beta=extracted.get("beta"),
        management_fee=extracted.get("management_fee"),
        performance_fee=extracted.get("performance_fee"),
        liquidity_terms=extracted.get("liquidity_terms"),
        redemption_notice=extracted.get("redemption_notice"),
        benchmark_name=extracted.get("benchmark_name"),
    )
    db.add(snapshot)

    # Save top positions
    for i, pos in enumerate(extracted.get("top_positions") or []):
        if not pos.get("name"):
            continue
        db.add(FundPosition(
            id=uuid.uuid4(),
            fund_id=fund.id,
            tenant_id=tenant_uuid,
            document_id=doc_uuid,
            report_date=report_date,
            period=extracted.get("period"),
            position_name=pos["name"],
            ticker=pos.get("ticker"),
            sector=pos.get("sector"),
            direction=pos.get("direction", "long"),
            weight_pct=pos.get("weight_pct"),
            rank=pos.get("rank", i + 1),
        ))

    # Save personnel changes
    for change in extracted.get("personnel_changes") or []:
        if not change.get("name"):
            continue
        eff_date = None
        if change.get("effective_date"):
            try:
                from datetime import datetime
                eff_date = datetime.strptime(change["effective_date"], "%Y-%m-%d").date()
            except Exception:
                pass
        db.add(PersonnelChange(
            id=uuid.uuid4(),
            fund_id=fund.id,
            tenant_id=tenant_uuid,
            document_id=doc_uuid,
            person_name=change["name"],
            previous_role=change.get("previous_role"),
            new_role=change.get("new_role"),
            change_type=change.get("change_type"),
            effective_date=eff_date,
        ))

    await db.flush()
    logger.info("Structured data saved", fund_name=fund_name, doc_id=doc_id)
    return str(fund.id)
