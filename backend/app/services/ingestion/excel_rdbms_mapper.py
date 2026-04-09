"""
Excel → RDBMS Mapper with LLM-Assisted Schema Detection
=========================================================
Flow:
  1. Read Excel with openpyxl (native, preserves all values)
  2. For each sheet: send headers + sample rows to LLM
  3. LLM maps columns to canonical financial schema
  4. Store mapped data in PostgreSQL tables
  5. Also returns full text for vector indexing

Canonical schemas detected:
  - returns        : fund returns by period (MTD/QTD/YTD/1Y/3Y)
  - positions      : top holdings with weights
  - aum            : AUM over time
  - risk_metrics   : volatility, sharpe, drawdown, beta
  - fees           : management fee, perf fee, hurdle
  - liquidity      : redemption terms, lockup, notice
  - exposure       : long/short/net/gross exposure by sector
  - personnel      : key people and changes
  - unknown        : stored as generic key-value, still queryable
"""
import io
import json
import re
import uuid
import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Schema detection prompt ───────────────────────────────────────────────────

SCHEMA_DETECTION_PROMPT = """You are a financial data schema expert.

I have an Excel sheet named "{sheet_name}" with these column headers:
{headers}

Here are the first 3 data rows as samples:
{sample_rows}

Identify what type of financial data this sheet contains and map each column.

Return ONLY valid JSON in this exact format:
{{
  "sheet_type": "returns|positions|aum|risk_metrics|fees|liquidity|exposure|personnel|unknown",
  "fund_name_column": "column name or null",
  "period_column": "column name or null",
  "date_column": "column name or null",
  "column_mappings": {{
    "original_column_name": "canonical_field_name",
    ...
  }}
}}

Canonical field names by sheet type:
- returns: fund_name, period, return_mtd, return_qtd, return_ytd, return_1yr, return_3yr, return_5yr, return_inception, benchmark_return
- positions: fund_name, period, rank, position_name, ticker, sector, weight_pct, direction, asset_class, market_value
- aum: fund_name, period, aum_usd, aum_raw, currency, investor_count
- risk_metrics: fund_name, period, volatility, sharpe_ratio, max_drawdown, beta, calmar_ratio, sortino_ratio, var_95
- fees: fund_name, management_fee, performance_fee, hurdle_rate, high_watermark, admin_fee
- liquidity: fund_name, liquidity_terms, redemption_notice, lockup_period, redemption_frequency, gate_provision
- exposure: fund_name, period, sector, long_pct, short_pct, net_pct, gross_pct, asset_class
- personnel: fund_name, person_name, role, previous_role, change_type, effective_date, education, years_experience
- unknown: key, value, notes

Return ONLY the JSON, no explanation."""


async def detect_sheet_schema(
    sheet_name: str,
    headers: list[str],
    sample_rows: list[list],
    settings,
) -> dict:
    """Ask LLM to identify what this Excel sheet contains."""
    headers_str = ", ".join(f'"{h}"' for h in headers if h)
    sample_str = "\n".join(
        "  Row {}: {}".format(i + 1, ", ".join(f'"{str(v)}"' for v in row[:8]))
        for i, row in enumerate(sample_rows[:3])
    )

    prompt = SCHEMA_DETECTION_PROMPT.format(
        sheet_name=sheet_name,
        headers=headers_str,
        sample_rows=sample_str,
    )

    try:
        if settings.llm_provider.lower() == "ollama":
            return await _llm_ollama(prompt, settings)
        elif settings.llm_provider.lower() == "openai":
            return await _llm_openai(prompt, settings)
        elif settings.llm_provider.lower() == "azure":
            return await _llm_azure(prompt, settings)
        else:
            return await _llm_ollama(prompt, settings)
    except Exception as exc:
        logger.warning("Schema detection failed, using unknown", sheet=sheet_name, error=str(exc))
        return {"sheet_type": "unknown", "column_mappings": {h: "value" for h in headers}}


async def _llm_ollama(prompt: str, settings) -> dict:
    import httpx
    payload = {
        "model": settings.ollama_chat_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0},
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _parse_json(content)


async def _llm_openai(prompt: str, settings) -> dict:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)


async def _llm_azure(prompt: str, settings) -> dict:
    from openai import AsyncAzureOpenAI
    client = AsyncAzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    resp = await client.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)


def _parse_json(content: str) -> dict:
    content = re.sub(r'^```json\s*', '', content.strip())
    content = re.sub(r'\s*```$', '', content)
    try:
        return json.loads(content)
    except Exception:
        return {"sheet_type": "unknown", "column_mappings": {}}


# ── Value normalizers ─────────────────────────────────────────────────────────

def _to_float(val) -> Optional[float]:
    """Convert percentage strings, numbers to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("%", "").replace(",", "").replace("$", "").replace("B", "e9").replace("M", "e6").replace("K", "e3")
    try:
        return float(s)
    except Exception:
        return None


def _to_date(val) -> Optional[date]:
    """Convert various date formats to date object."""
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    s = str(val).strip()
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%b %Y", "%B %Y", "%b-%y", "%Y"]:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _to_str(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


# ── RDBMS insertion functions ─────────────────────────────────────────────────

async def _store_returns(rows: list[dict], schema: dict, fund_id: uuid.UUID,
                          tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    from app.models.structured_data import FundSnapshot
    mappings = schema.get("column_mappings", {})
    stored = 0
    for row in rows:
        mapped = {mappings.get(k, k): v for k, v in row.items()}
        snap = FundSnapshot(
            id=uuid.uuid4(),
            fund_id=fund_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            period=_to_str(mapped.get("period")),
            report_date=_to_date(mapped.get("period") or mapped.get("date")),
            return_mtd=_to_float(mapped.get("return_mtd")),
            return_qtd=_to_float(mapped.get("return_qtd")),
            return_ytd=_to_float(mapped.get("return_ytd")),
            return_1yr=_to_float(mapped.get("return_1yr")),
            return_3yr=_to_float(mapped.get("return_3yr")),
            return_5yr=_to_float(mapped.get("return_5yr") or mapped.get("return_5y")),
            return_inception=_to_float(mapped.get("return_inception")),
            benchmark_return_1yr=_to_float(mapped.get("benchmark_return")),
        )
        db.add(snap)
        stored += 1
    return stored


async def _store_positions(rows: list[dict], schema: dict, fund_id: uuid.UUID,
                            tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    from app.models.structured_data import FundPosition
    mappings = schema.get("column_mappings", {})
    stored = 0
    for i, row in enumerate(rows):
        mapped = {mappings.get(k, k): v for k, v in row.items()}
        name = _to_str(mapped.get("position_name"))
        if not name:
            continue
        pos = FundPosition(
            id=uuid.uuid4(),
            fund_id=fund_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            period=_to_str(mapped.get("period")),
            report_date=_to_date(mapped.get("period") or mapped.get("date")),
            position_name=name,
            ticker=_to_str(mapped.get("ticker")),
            sector=_to_str(mapped.get("sector")),
            asset_class=_to_str(mapped.get("asset_class")),
            direction=_to_str(mapped.get("direction")) or "long",
            weight_pct=_to_float(mapped.get("weight_pct")),
            rank=int(mapped.get("rank") or i + 1),
        )
        db.add(pos)
        stored += 1
    return stored


async def _store_risk(rows: list[dict], schema: dict, fund_id: uuid.UUID,
                       tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    from app.models.structured_data import FundSnapshot
    from sqlalchemy import select, desc
    mappings = schema.get("column_mappings", {})
    stored = 0
    for row in rows:
        mapped = {mappings.get(k, k): v for k, v in row.items()}
        # Try to find existing snapshot for same period to update
        period = _to_str(mapped.get("period"))
        existing = await db.execute(
            select(FundSnapshot).where(
                FundSnapshot.fund_id == fund_id,
                FundSnapshot.period == period,
            ).limit(1)
        )
        snap = existing.scalar_one_or_none()
        if not snap:
            snap = FundSnapshot(
                id=uuid.uuid4(), fund_id=fund_id,
                tenant_id=tenant_id, document_id=doc_id,
                period=period,
            )
            db.add(snap)
        snap.volatility = _to_float(mapped.get("volatility")) or snap.volatility
        snap.sharpe_ratio = _to_float(mapped.get("sharpe_ratio")) or snap.sharpe_ratio
        snap.max_drawdown = _to_float(mapped.get("max_drawdown")) or snap.max_drawdown
        snap.beta = _to_float(mapped.get("beta")) or snap.beta
        snap.calmar_ratio = _to_float(mapped.get("calmar_ratio")) or snap.calmar_ratio
        stored += 1
    return stored


async def _store_fees(rows: list[dict], schema: dict, fund_id: uuid.UUID,
                       tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    from app.models.structured_data import FundSnapshot
    from sqlalchemy import select
    mappings = schema.get("column_mappings", {})
    stored = 0
    for row in rows:
        mapped = {mappings.get(k, k): v for k, v in row.items()}
        # Update latest snapshot or create one
        existing = await db.execute(
            select(FundSnapshot).where(FundSnapshot.fund_id == fund_id).limit(1)
        )
        snap = existing.scalar_one_or_none()
        if not snap:
            snap = FundSnapshot(id=uuid.uuid4(), fund_id=fund_id, tenant_id=tenant_id, document_id=doc_id)
            db.add(snap)
        snap.management_fee = _to_float(mapped.get("management_fee")) or snap.management_fee
        snap.performance_fee = _to_float(mapped.get("performance_fee")) or snap.performance_fee
        snap.hurdle_rate = _to_float(mapped.get("hurdle_rate")) or snap.hurdle_rate
        stored += 1
    return stored


async def _store_aum(rows: list[dict], schema: dict, fund_id: uuid.UUID,
                      tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    from app.models.structured_data import FundSnapshot
    mappings = schema.get("column_mappings", {})
    stored = 0
    for row in rows:
        mapped = {mappings.get(k, k): v for k, v in row.items()}
        aum_raw = _to_str(mapped.get("aum_raw")) or _to_str(mapped.get("aum_usd"))
        aum_float = _to_float(mapped.get("aum_usd") or mapped.get("aum_raw"))
        if not aum_float and not aum_raw:
            continue
        snap = FundSnapshot(
            id=uuid.uuid4(), fund_id=fund_id,
            tenant_id=tenant_id, document_id=doc_id,
            period=_to_str(mapped.get("period")),
            report_date=_to_date(mapped.get("period") or mapped.get("date")),
            aum_usd=aum_float,
            aum_raw=aum_raw,
        )
        db.add(snap)
        stored += 1
    return stored


async def _store_personnel(rows: list[dict], schema: dict, fund_id: uuid.UUID,
                            tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    from app.models.structured_data import PersonnelChange
    mappings = schema.get("column_mappings", {})
    stored = 0
    for row in rows:
        mapped = {mappings.get(k, k): v for k, v in row.items()}
        name = _to_str(mapped.get("person_name"))
        if not name:
            continue
        db.add(PersonnelChange(
            id=uuid.uuid4(), fund_id=fund_id,
            tenant_id=tenant_id, document_id=doc_id,
            person_name=name,
            previous_role=_to_str(mapped.get("previous_role")),
            new_role=_to_str(mapped.get("role") or mapped.get("new_role")),
            change_type=_to_str(mapped.get("change_type")),
            effective_date=_to_date(mapped.get("effective_date")),
            notes=_to_str(mapped.get("notes")),
        ))
        stored += 1
    return stored


async def _store_generic(sheet_name: str, rows: list[dict], fund_id: uuid.UUID,
                          tenant_id: uuid.UUID, doc_id: uuid.UUID, db) -> int:
    """Store unknown sheets as generic key-value in fund_raw_data."""
    from app.models.structured_data import FundRawData
    try:
        db.add(FundRawData(
            id=uuid.uuid4(), fund_id=fund_id,
            tenant_id=tenant_id, document_id=doc_id,
            sheet_name=sheet_name,
            data=rows,
        ))
        return len(rows)
    except Exception:
        return 0  # FundRawData might not exist yet, non-fatal


# ── Main entry point ──────────────────────────────────────────────────────────

async def map_excel_to_rdbms(
    file_bytes: bytes,
    filename: str,
    doc_id: str,
    tenant_id: str,
    db,
    settings,
) -> dict:
    """
    Main function: reads Excel, detects schema per sheet via LLM,
    stores all data in PostgreSQL. Returns summary.
    """
    try:
        import openpyxl
    except ImportError:
        return {"error": "openpyxl not installed"}

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        return {"error": str(exc)}

    from app.models.structured_data import Fund
    from sqlalchemy import select

    tenant_uuid = uuid.UUID(tenant_id)
    doc_uuid = uuid.UUID(doc_id)

    # Get or create fund (use filename as fund name hint initially)
    fund_name_hint = Path(filename).stem.replace("_", " ").replace("-", " ")
    result = await db.execute(
        select(Fund).where(Fund.tenant_id == tenant_uuid).order_by(Fund.created_at.desc()).limit(1)
    )
    fund = result.scalar_one_or_none()
    if not fund:
        fund = Fund(id=uuid.uuid4(), tenant_id=tenant_uuid, fund_name=fund_name_hint)
        db.add(fund)
        await db.flush()

    summary = {"filename": filename, "sheets_processed": [], "total_rows_stored": 0}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        all_rows = [row for row in ws.iter_rows(values_only=True)
                    if not all(c is None or str(c).strip() == "" for c in row)]

        if len(all_rows) < 2:
            continue

        headers = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(all_rows[0])]
        data_rows = [dict(zip(headers, row)) for row in all_rows[1:]]
        sample_rows = [list(row) for row in all_rows[1:4]]

        # LLM detects schema
        logger.info("Detecting schema", sheet=sheet_name, headers=headers[:8])
        schema = await detect_sheet_schema(sheet_name, headers, sample_rows, settings)
        sheet_type = schema.get("sheet_type", "unknown")

        logger.info("Schema detected", sheet=sheet_name, type=sheet_type)

        # Update fund name if LLM found it in a column
        fund_col = schema.get("fund_name_column")
        if fund_col and data_rows and fund_col in data_rows[0]:
            detected_name = _to_str(data_rows[0][fund_col])
            if detected_name and detected_name != fund.fund_name:
                # Check if we should update or create new fund
                result2 = await db.execute(
                    select(Fund).where(Fund.fund_name.ilike(f"%{detected_name}%"), Fund.tenant_id == tenant_uuid).limit(1)
                )
                existing_fund = result2.scalar_one_or_none()
                if existing_fund:
                    fund = existing_fund
                else:
                    fund.fund_name = detected_name

        # Store by type
        try:
            if sheet_type == "returns":
                stored = await _store_returns(data_rows, schema, fund.id, tenant_uuid, doc_uuid, db)
            elif sheet_type == "positions":
                stored = await _store_positions(data_rows, schema, fund.id, tenant_uuid, doc_uuid, db)
            elif sheet_type == "risk_metrics":
                stored = await _store_risk(data_rows, schema, fund.id, tenant_uuid, doc_uuid, db)
            elif sheet_type == "fees":
                stored = await _store_fees(data_rows, schema, fund.id, tenant_uuid, doc_uuid, db)
            elif sheet_type == "aum":
                stored = await _store_aum(data_rows, schema, fund.id, tenant_uuid, doc_uuid, db)
            elif sheet_type == "personnel":
                stored = await _store_personnel(data_rows, schema, fund.id, tenant_uuid, doc_uuid, db)
            else:
                stored = await _store_generic(sheet_name, data_rows, fund.id, tenant_uuid, doc_uuid, db)

            summary["sheets_processed"].append({
                "sheet": sheet_name,
                "type": sheet_type,
                "rows_stored": stored,
            })
            summary["total_rows_stored"] += stored

        except Exception as exc:
            logger.warning("Sheet storage failed", sheet=sheet_name, error=str(exc))
            summary["sheets_processed"].append({"sheet": sheet_name, "type": sheet_type, "error": str(exc)})

    await db.flush()
    wb.close()

    logger.info("Excel RDBMS mapping complete", filename=filename,
                sheets=len(summary["sheets_processed"]),
                rows=summary["total_rows_stored"])
    return summary
