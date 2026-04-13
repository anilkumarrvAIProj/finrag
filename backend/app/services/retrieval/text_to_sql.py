"""
Text-to-SQL Service
Converts natural language queries to SQL and executes against PostgreSQL.

The LLM is given a compact schema description and asked to write a SQL query.
Results are returned as structured data for the response formatter.

Handles queries like:
  - "Compare YTD returns for all funds as of March 2025"
  - "Which fund has the lowest management fee?"
  - "Show me top 5 positions for Aether fund in Q4 2024"
  - "What was AUM trend for Caligan over last 4 quarters?"
  - "List all personnel changes in 2025"
"""
import json
import re
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Schema description sent to LLM ───────────────────────────────────────────

DB_SCHEMA = """
PostgreSQL tables available:

funds(id UUID, name TEXT, slug TEXT, strategy TEXT, description TEXT)

fund_snapshots(id UUID, fund_id UUID, period TEXT, report_date DATE,
  aum_usd FLOAT, aum_raw TEXT,
  return_mtd FLOAT, return_qtd FLOAT, return_ytd FLOAT,
  return_1yr FLOAT, return_3yr FLOAT, return_5yr FLOAT, return_inception FLOAT,
  volatility FLOAT, sharpe_ratio FLOAT, max_drawdown FLOAT, beta FLOAT, calmar_ratio FLOAT,
  management_fee FLOAT, performance_fee FLOAT, hurdle_rate FLOAT,
  liquidity_terms TEXT, redemption_notice TEXT, lockup_period TEXT,
  benchmark_name TEXT, benchmark_return_1yr FLOAT)

fund_positions(id UUID, fund_id UUID, period TEXT, report_date DATE,
  position_name TEXT, ticker TEXT, sector TEXT, asset_class TEXT,
  direction TEXT, weight_pct FLOAT, rank INTEGER)

personnel_changes(id UUID, fund_id UUID,
  person_name TEXT, previous_role TEXT, new_role TEXT,
  change_type TEXT, effective_date DATE, notes TEXT)

fund_raw_data(id UUID, fund_id UUID, sheet_name TEXT, data JSONB)

All tables join via fund_id → funds.id
Use funds.name for filtering by fund name (use ILIKE for fuzzy match)
Return amounts are as percentages (1.5 means 1.5%)
AUM is in USD millions unless aum_raw has the original string
"""

TEXT_TO_SQL_PROMPT = """You are a PostgreSQL expert for a financial analytics platform.

{schema}

Convert this question to a SQL query:
"{question}"

Rules:
1. Return ONLY the SQL query, no explanation
2. Always join with funds table using funds.name (NOT fund_name)
3. Use ILIKE for fund name matching
4. Order results meaningfully (by date DESC for time series, by value DESC for rankings)
5. Limit to 50 rows maximum
6. Use ROUND(value::numeric, 2) for float columns
7. Format dates as TO_CHAR(date_col, 'Mon YYYY')
8. If period is like "Q1 2025" filter with period ILIKE '%2025%' 
9. Only use tables and columns defined in the schema above
10. If question cannot be answered with these tables, return: SELECT 'Data not available in structured store' as message

SQL:"""


async def query_to_sql(question: str, settings) -> Optional[str]:
    """Ask LLM to convert question to SQL."""
    prompt = TEXT_TO_SQL_PROMPT.format(schema=DB_SCHEMA, question=question)

    try:
        if settings.llm_provider.lower() == "ollama":
            sql = await _sql_ollama(prompt, settings)
        elif settings.llm_provider.lower() == "openai":
            sql = await _sql_openai(prompt, settings)
        elif settings.llm_provider.lower() == "azure":
            sql = await _sql_azure(prompt, settings)
        else:
            sql = await _sql_ollama(prompt, settings)

        # Clean up the SQL
        sql = _clean_sql(sql)
        logger.info("Generated SQL", question=question[:60], sql=sql[:100])
        return sql
    except Exception as exc:
        logger.warning("Text-to-SQL failed", error=str(exc))
        return None


async def _sql_ollama(prompt: str, settings) -> str:
    import httpx
    payload = {
        "model": settings.ollama_chat_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def _sql_openai(prompt: str, settings) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return resp.choices[0].message.content


async def _sql_azure(prompt: str, settings) -> str:
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
    )
    return resp.choices[0].message.content


def _clean_sql(sql: str) -> str:
    """Strip markdown fences and normalize whitespace."""
    sql = re.sub(r'^```sql\s*', '', sql.strip(), flags=re.IGNORECASE)
    sql = re.sub(r'^```\s*', '', sql.strip())
    sql = re.sub(r'\s*```$', '', sql)
    # Remove any non-SQL prefix text
    lines = sql.strip().split('\n')
    sql_lines = []
    in_sql = False
    for line in lines:
        if any(line.strip().upper().startswith(kw) for kw in ['SELECT', 'WITH', 'INSERT', 'UPDATE']):
            in_sql = True
        if in_sql:
            sql_lines.append(line)
    return '\n'.join(sql_lines) if sql_lines else sql.strip()


async def execute_sql_query(sql: str, db) -> list[dict]:
    """Execute SQL against PostgreSQL and return rows as list of dicts."""
    from sqlalchemy import text
    try:
        result = await db.execute(text(sql))
        columns = list(result.keys())
        rows = []
        for row in result.fetchall():
            rows.append(dict(zip(columns, row)))
        return rows
    except Exception as exc:
        logger.error("SQL execution failed", sql=sql[:200], error=str(exc))
        raise


def format_sql_results(rows: list[dict], question: str) -> str:
    """Format SQL query results as a clean markdown table."""
    if not rows:
        return "No data found for this query."

    if len(rows) == 1 and "message" in rows[0]:
        return rows[0]["message"]

    columns = list(rows[0].keys())

    # Build markdown table
    parts = []

    # Header
    parts.append("| " + " | ".join(str(c).replace("_", " ").title() for c in columns) + " |")
    parts.append("|" + "|".join(["---"] * len(columns)) + "|")

    # Data rows
    for row in rows:
        cells = []
        for col in columns:
            val = row[col]
            if val is None:
                cells.append("—")
            elif isinstance(val, float):
                # Format percentages and ratios nicely
                if any(k in col.lower() for k in ["return", "fee", "volatility", "drawdown", "weight"]):
                    cells.append(f"{val:+.2f}%")
                else:
                    cells.append(f"{val:.2f}")
            else:
                cells.append(str(val))
        parts.append("| " + " | ".join(cells) + " |")

    return "\n".join(parts)


def should_use_sql(query: str) -> bool:
    """
    Determine if this query should go to Text-to-SQL vs RAG.
    SQL is better for: comparisons, rankings, exact numbers, trends over time.
    RAG is better for: explanations, qualitative analysis, strategy descriptions.
    """
    q = query.lower()

    sql_indicators = [
        "compare", "comparison", "vs", "versus", "all funds", "across funds",
        "which fund", "highest", "lowest", "best", "worst", "rank",
        "how many", "total", "average", "sum", "trend", "over time",
        "last 4 quarter", "last 12 month", "since inception",
        "top 5", "top 10", "bottom 5",
        "list all", "show all", "give me all",
        "ytd return", "1yr return", "management fee", "performance fee",
        "aum", "assets under management",
        "position", "holding", "exposure",
        "personnel", "who joined", "who left",
    ]

    rag_indicators = [
        "explain", "why", "how does", "what is the strategy",
        "describe", "tell me about", "what is their approach",
        "philosophy", "process", "methodology",
    ]

    sql_score = sum(1 for k in sql_indicators if k in q)
    rag_score = sum(1 for k in rag_indicators if k in q)

    return sql_score > rag_score
