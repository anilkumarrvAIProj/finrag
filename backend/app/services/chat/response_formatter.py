"""
Response Formatter
==================
Rules:
  - Comparisons, performance, positions, fees → always Markdown table
  - Narrative/qualitative → structured paragraphs
  - Sources always at bottom, separated by ---
  - Never mix sources inline with the answer
"""
import re
from typing import Optional


# ── Query type detection ──────────────────────────────────────────────────────

def detect_query_type(query: str) -> tuple[str, Optional[str]]:
    q = query.lower()

    fund_hint = None
    # Known fund/manager keywords to search around
    for keyword in ["position", "holding", "aum", "asset", "fee", "liquidity",
                     "performance", "return", "personnel", "manager", "change",
                     "compare", "vs", "versus", "investor", "number of", "how many"]:
        if keyword in q:
            idx = q.find(keyword)
            # Try before the keyword first
            before = query[:idx].strip().rstrip("'s").strip()
            if 3 < len(before) < 80:
                fund_hint = before
            else:
                # Try after the keyword
                after = query[idx + len(keyword):].strip()
                # Strip leading prepositions
                import re as _re
                after = _re.sub("^(for|in|of|about|on) ", "", after, flags=_re.IGNORECASE)
                if 3 < len(after) < 80:
                    fund_hint = after
            break

    if any(k in q for k in ["top position", "top holding", "largest position", "top 5", "top 10"]):
        qoq = any(k in q for k in ["qoq", "quarter over quarter", "compare", "vs last"])
        return ("top_positions_qoq" if qoq else "top_positions"), fund_hint

    if any(k in q for k in ["management fee", "performance fee", "fee structure", "what is the fee", "fees"]):
        return "fees", fund_hint

    if any(k in q for k in ["liquidity", "redemption", "lockup", "withdrawal"]):
        return "liquidity", fund_hint

    if any(k in q for k in ["aum", "assets under management", "fund size"]):
        return "aum", fund_hint

    if any(k in q for k in ["personnel", "key person", "manager change", "who joined", "who left"]):
        return "personnel", fund_hint

    if any(k in q for k in ["qoq", "quarter over quarter", "last 4 quarter", "sentiment"]):
        return "qoq_history", fund_hint

    if any(k in q for k in ["performance", "return", "ytd", "1yr", "1 year", "3yr",
                              "compare", "vs", "versus", "how did", "how has"]):
        return "performance", fund_hint

    return "general", fund_hint


def is_tabular_query(query: str) -> bool:
    """Return True if this query should always produce a table."""
    q = query.lower()
    return any(k in q for k in [
        "compare", "vs", "versus", "comparison",
        "top 5", "top 10", "top position", "top holding",
        "performance", "return", "ytd", "1yr", "1 year", "3yr",
        "fees", "management fee", "performance fee",
        "aum", "liquidity",
        "all funds", "across funds", "which fund",
        "qoq", "quarter over quarter",
        "list", "show me", "give me",
    ])


# ── Structured data formatters ────────────────────────────────────────────────

def format_structured_response(
    data: dict,
    query_type: str,
    fund_name: str,
    web_sources: list = None,
    rag_citations: list = None,
    extra_context: str = "",
) -> str:
    parts = []

    if query_type in ("top_positions", "top_positions_qoq"):
        parts.append(f"## Top {len(data.get('positions', []))} positions — {fund_name}")
        if data.get("latest_period"):
            parts.append(f"*Period: {data['latest_period']}*")
        parts.append("")
        if data.get("previous_period"):
            parts.append("| Rank | Position | Weight | Direction | vs prev period |")
            parts.append("|------|----------|--------|-----------|----------------|")
            prev_map = {p["name"]: p for p in data.get("previous_positions", [])}
            for pos in data["positions"]:
                prev = prev_map.get(pos["name"])
                change = (f"{pos['weight_pct'] - prev['weight_pct']:+.1f}%"
                          if prev and pos.get("weight_pct") and prev.get("weight_pct")
                          else ("New" if not prev else "—"))
                weight = f"{pos['weight_pct']:.1f}%" if pos.get("weight_pct") else "—"
                parts.append(f"| {pos['rank']} | {pos['name']} | {weight} | {pos.get('direction','long').title()} | {change} |")
        else:
            parts.append("| Rank | Position | Weight | Direction |")
            parts.append("|------|----------|--------|-----------|")
            for pos in data["positions"]:
                weight = f"{pos['weight_pct']:.1f}%" if pos.get("weight_pct") else "—"
                parts.append(f"| {pos['rank']} | {pos['name']} | {weight} | {pos.get('direction','long').title()} |")

    elif query_type == "fees":
        parts.append(f"## Fee structure — {fund_name}")
        if data.get("period"):
            parts.append(f"*As of: {data['period']}*")
        parts.append("")
        parts.append("| Fee type | Rate |")
        parts.append("|----------|------|")
        if data.get("management_fee") is not None:
            parts.append(f"| Management fee | {data['management_fee']:.2f}% |")
        if data.get("performance_fee") is not None:
            parts.append(f"| Performance fee | {data['performance_fee']:.0f}% |")
        if data.get("hurdle_rate") is not None:
            parts.append(f"| Hurdle rate | {data['hurdle_rate']:.1f}% |")

    elif query_type == "liquidity":
        parts.append(f"## Liquidity terms — {fund_name}")
        parts.append("")
        parts.append("| Term | Detail |")
        parts.append("|------|--------|")
        if data.get("liquidity_terms"):
            parts.append(f"| Liquidity | {data['liquidity_terms']} |")
        if data.get("redemption_notice"):
            parts.append(f"| Redemption notice | {data['redemption_notice']} |")
        if data.get("lockup_period"):
            parts.append(f"| Lockup period | {data['lockup_period']} |")

    elif query_type == "aum":
        parts.append(f"## AUM — {fund_name}")
        if data.get("period"):
            parts.append(f"*As of: {data['period']}*")
        parts.append("")
        aum = data.get("aum_raw") or (f"${data['aum_usd']:.0f}M" if data.get("aum_usd") else "Not available")
        parts.append(f"**AUM:** {aum}")

    elif query_type == "performance":
        parts.append(f"## Performance — {fund_name}")
        if data.get("period"):
            parts.append(f"*As of: {data['period']}*")
        parts.append("")
        parts.append("| Period | Fund return | Benchmark |")
        parts.append("|--------|-------------|-----------|")
        metrics = [
            ("MTD", data.get("return_mtd")),
            ("QTD", data.get("return_qtd")),
            ("YTD", data.get("return_ytd")),
            ("1 year", data.get("return_1yr")),
            ("3 year", data.get("return_3yr")),
            ("Since inception", data.get("return_inception")),
        ]
        bench_name = data.get("benchmark_name", "Benchmark")
        bench_1yr = data.get("benchmark_return_1yr")
        for label, val in metrics:
            if val is not None:
                bench = (f"{bench_1yr:+.1f}%" if bench_1yr and label == "1 year" else "—")
                parts.append(f"| {label} | {val:+.1f}% | {bench} |")

    elif query_type == "personnel":
        parts.append(f"## Personnel changes — {fund_name}")
        parts.append(f"*Last {data.get('period_months', 12)} months*")
        parts.append("")
        changes = data.get("changes", [])
        if not changes:
            parts.append("No personnel changes found in the specified period.")
        else:
            parts.append("| Name | Change | Previous role | New role | Effective date |")
            parts.append("|------|--------|---------------|----------|----------------|")
            for c in changes:
                parts.append(f"| {c['name']} | {c.get('change_type','—').title()} | {c.get('previous_role','—')} | {c.get('new_role','—')} | {c.get('effective_date','—')} |")

    elif query_type == "qoq_history":
        parts.append(f"## Quarterly performance — {fund_name}")
        parts.append("")
        parts.append("| Period | QTD return | YTD return | AUM |")
        parts.append("|--------|------------|------------|-----|")
        for h in data.get("history", []):
            qtd = f"{h['return_qtd']:+.1f}%" if h.get("return_qtd") is not None else "—"
            ytd = f"{h['return_ytd']:+.1f}%" if h.get("return_ytd") is not None else "—"
            parts.append(f"| {h.get('period','—')} | {qtd} | {ytd} | {h.get('aum_raw','—')} |")

    if extra_context:
        parts.append("")
        parts.append("### Additional context")
        parts.append(extra_context)

    parts.extend(_format_sources(rag_citations, web_sources))
    return "\n".join(parts)


def format_sql_results(rows: list[dict], question: str = "") -> str:
    """Format SQL rows as a clean markdown table."""
    if not rows:
        return "No data found for this query in the structured database."

    if len(rows) == 1 and "message" in rows[0]:
        return rows[0]["message"]

    columns = list(rows[0].keys())
    parts = []
    parts.append("| " + " | ".join(c.replace("_", " ").title() for c in columns) + " |")
    parts.append("|" + "|".join(["---"] * len(columns)) + "|")

    for row in rows:
        cells = []
        for col in columns:
            val = row[col]
            if val is None:
                cells.append("—")
            elif isinstance(val, float):
                if any(k in col.lower() for k in ["return", "fee", "volatility", "drawdown", "weight", "pct"]):
                    cells.append(f"{val:+.2f}%")
                else:
                    cells.append(f"{val:.2f}")
            else:
                cells.append(str(val))
        parts.append("| " + " | ".join(cells) + " |")

    return "\n".join(parts)


def enforce_table_format(llm_text: str, query: str) -> str:
    """
    Post-process LLM free text response for tabular queries.
    If the LLM returned a table already → keep it.
    If it returned prose for a query that should be tabular → reformat.
    """
    if not is_tabular_query(query):
        return llm_text

    # Already has a markdown table → good, return as-is
    if "|" in llm_text and "---" in llm_text:
        return _ensure_sources_at_bottom(llm_text)

    # LLM returned prose — try to extract numbers and build a table
    q = query.lower()

    # Performance comparison pattern — look for fund+number pairs
    if any(k in q for k in ["compare", "vs", "versus", "performance", "return", "1yr", "1 year"]):
        table = _extract_performance_table(llm_text, query)
        if table:
            return table

    # Can't convert — return original but move sources to bottom
    return _ensure_sources_at_bottom(llm_text)


def _extract_performance_table(text: str, query: str) -> Optional[str]:
    """
    Try to extract fund name + return value pairs from prose and build a table.
    Example prose: "Aether Global Macro returned 12.3% while L/S Equity returned 8.1%"
    """
    # Pattern: word(s) followed by a percentage
    pattern = r'([A-Z][A-Za-z\s/&]+?)\s*(?:returned?|performance|return(?:ed)?(?:\s+was)?|:)\s*([+-]?\d+\.?\d*)\s*%'
    matches = re.findall(pattern, text)

    if len(matches) < 2:
        # Try simpler pattern: just find all percentages with context
        pattern2 = r'([A-Z][A-Za-z\s]+?)[\s:]+([+-]?\d+\.?\d*)\s*%'
        matches = re.findall(pattern2, text)

    if len(matches) < 1:
        return None

    parts = []
    # Extract period from query
    period = "1 year"
    for p in ["1yr", "1 year", "ytd", "3yr", "3 year", "inception", "qtd", "mtd"]:
        if p in query.lower():
            period = p.upper().replace("YR", " year").replace("TD", "TD")
            break

    parts.append(f"| Fund | {period} return |")
    parts.append("|------|--------------|")
    for name, pct in matches[:10]:
        name = name.strip().rstrip("'s").strip()
        if len(name) > 3:
            try:
                val = float(pct)
                parts.append(f"| {name} | {val:+.1f}% |")
            except Exception:
                parts.append(f"| {name} | {pct}% |")

    if len(parts) <= 2:
        return None

    # Add any narrative context that isn't number-extraction
    narrative = re.sub(pattern, '', text).strip()
    narrative = re.sub(r'\s+', ' ', narrative).strip()
    if len(narrative) > 50:
        parts.append("")
        parts.append(narrative[:500])

    return "\n".join(parts)


def _ensure_sources_at_bottom(text: str) -> str:
    """Move any inline source citations to a clean section at the bottom."""
    # Already has a sources section
    if "---\n**Sources**" in text or "---\n### Sources" in text:
        return text

    # Extract inline sources like [1] filename, Page N
    source_pattern = r'(?:Sources?:|Citations?:)\s*\[?\d+\]?[^\n]+'
    sources = re.findall(source_pattern, text, re.IGNORECASE)

    if sources:
        # Remove inline sources from body
        clean = re.sub(source_pattern, '', text, flags=re.IGNORECASE).strip()
        clean += "\n\n---\n**Sources**\n"
        for s in sources:
            clean += f"- {s.strip()}\n"
        return clean

    return text


def _format_sources(rag_citations: list, web_sources: list) -> list[str]:
    """Format sources as clean footnotes at the bottom."""
    sources = []
    if rag_citations:
        for c in rag_citations:
            sources.append(f"[{c['ref']}] {c['filename']}, Page {c.get('page_start', '?')}")
    if web_sources:
        for s in web_sources:
            sources.append(f"[WEB-{s['ref']}] {s['title']} — {s['url']}")

    if not sources:
        return []

    return ["", "---", "**Sources**"] + [f"- {s}" for s in sources]


# Alias for backward compatibility
def format_sql_results_alias(rows, question=""):
    return format_sql_results(rows, question)





def clean_preamble(text: str) -> str:
    """
    Aggressively strip LLM filler from the start of responses.
    Works line by line — removes any opening line that is pure filler
    and doesn't contain actual answer content (numbers, fund names, table syntax).
    """
    import re

    lines = text.split("\n")
    result = []
    header_done = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if not header_done:
            # Skip empty lines at the start
            if not stripped:
                continue

            # Skip lines that are pure filler openers with no data
            is_filler = (
                lower.startswith("based on") or
                lower.startswith("according to") or
                lower.startswith("from the provided") or
                lower.startswith("from the context") or
                lower.startswith("the context") or
                lower.startswith("the documents") or
                lower.startswith("the provided") or
                lower.startswith("here are") or
                lower.startswith("here is") or
                lower.startswith("i found") or
                lower.startswith("as per") or
                lower.endswith("the answers:") or
                lower.endswith("the answer:") or
                lower.endswith("as follows:") or
                lower.endswith("the information:") or
                lower.endswith("the results:")
            )

            # But don't skip if line has actual data (numbers, %, table pipes, **)
            has_data = bool(re.search(r'[\d%|*#]', stripped))

            if is_filler and not has_data:
                continue  # skip this filler line

            header_done = True

        result.append(line)

    return "\n".join(result).strip()


def generate_response_title(query: str, response_text: str) -> str:
    """
    Generate a clean contextual title/opener for the response
    based on the question asked, instead of LLM filler phrases.
    """
    import re
    q = query.lower().strip().rstrip("?")

    # Performance / returns
    if any(k in q for k in ["1yr", "1 year", "return", "performance", "ytd"]):
        return "**Performance returns**\n\n"

    # Number of investors
    if "number of investor" in q or "investor count" in q or "how many investor" in q:
        return "**Number of investors**\n\n"

    # AUM
    if "aum" in q or "assets under management" in q or "fund size" in q:
        return "**Assets under management**\n\n"

    # Fees
    if "fee" in q or "management fee" in q or "performance fee" in q:
        return "**Fee structure**\n\n"

    # Positions / holdings
    if "position" in q or "holding" in q or "top 5" in q or "top 10" in q:
        return "**Top positions**\n\n"

    # Liquidity
    if "liquidity" in q or "redemption" in q or "lockup" in q:
        return "**Liquidity terms**\n\n"

    # Personnel
    if "personnel" in q or "manager" in q or "who joined" in q or "who left" in q:
        return "**Personnel changes**\n\n"

    # Comparison
    if "compare" in q or " vs " in q or "versus" in q:
        return "**Comparison**\n\n"

    # No title for general queries
    return ""


def apply_response_title(text: str, query: str) -> str:
    """
    Add a contextual title to the response if it doesn't already have one (##).
    """
    if text.startswith("#") or text.startswith("**"):
        return text  # already has a title
    title = generate_response_title(query, text)
    return title + text if title else text



def strip_inline_sources(text: str) -> str:
    """Remove inline Sources lines — the UI renders citations in its own panel."""
    import re
    lines = text.split("\n")
    result = []
    in_sources = False
    for line in lines:
        s = line.strip()
        # Detect start of sources block
        if s == "---":
            in_sources = True
            continue
        if in_sources:
            # Skip source-block content
            if re.match(r"^\*\*Sources\*\*", s) or re.match(r"^Sources", s, re.IGNORECASE):
                continue
            if re.match(r"^-\s*\[", s) or re.match(r"^\[\d+\]", s):
                continue
            if not s:
                continue
            # Non-source content after --- means end of sources block
            in_sources = False
        # Also strip bare inline "Sources: [1]..." lines anywhere
        if re.match(r"^Sources?:\s*\[", s, re.IGNORECASE):
            continue
        result.append(line)
    return "\n".join(result).rstrip()
