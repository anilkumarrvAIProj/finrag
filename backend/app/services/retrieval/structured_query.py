"""
Structured Query Service
Answers precise financial queries directly from PostgreSQL.
Used BEFORE vector search for questions about specific numbers.

Handles:
- Top N positions (QoQ comparison)
- AUM queries
- Fee queries
- Performance metrics
- Personnel changes timeline
- Fund vs benchmark comparisons
"""
import uuid
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import select, desc, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.structured_data import Fund, FundSnapshot, FundPosition, PersonnelChange
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def query_top_positions(
    db: AsyncSession,
    fund_name: Optional[str],
    top_n: int = 5,
    period: Optional[str] = None,
    compare_qoq: bool = False,
    tenant_id: uuid.UUID = DEFAULT_TENANT,
) -> Optional[dict]:
    """Get top N positions for a fund, optionally comparing QoQ."""

    # Find fund
    fund = await _get_fund(db, fund_name, tenant_id)
    if not fund:
        return None

    # Get latest period
    q = select(FundPosition).where(
        FundPosition.fund_id == fund.id,
        FundPosition.tenant_id == tenant_id,
    )
    if period:
        q = q.where(FundPosition.period == period)
    q = q.order_by(desc(FundPosition.report_date), FundPosition.rank).limit(top_n * 2)

    result = await db.execute(q)
    positions = result.scalars().all()

    if not positions:
        return None

    # Group by period
    periods = {}
    for pos in positions:
        key = pos.period or str(pos.report_date)
        if key not in periods:
            periods[key] = []
        if len(periods[key]) < top_n:
            periods[key].append(pos)

    period_keys = sorted(periods.keys(), reverse=True)
    latest = period_keys[0] if period_keys else None
    previous = period_keys[1] if len(period_keys) > 1 else None

    return {
        "fund_name": fund.fund_name,
        "latest_period": latest,
        "previous_period": previous if compare_qoq else None,
        "positions": [
            {
                "rank": p.rank,
                "name": p.position_name,
                "ticker": p.ticker,
                "direction": p.direction,
                "weight_pct": p.weight_pct,
                "sector": p.sector,
            }
            for p in periods.get(latest, [])
        ],
        "previous_positions": [
            {
                "rank": p.rank,
                "name": p.position_name,
                "weight_pct": p.weight_pct,
            }
            for p in periods.get(previous, [])
        ] if compare_qoq and previous else [],
    }


async def query_fund_metrics(
    db: AsyncSession,
    fund_name: Optional[str],
    metric: str,   # aum | performance | fees | risk | liquidity
    tenant_id: uuid.UUID = DEFAULT_TENANT,
) -> Optional[dict]:
    """Get specific metrics for a fund from latest snapshot."""

    fund = await _get_fund(db, fund_name, tenant_id)
    if not fund:
        return None

    result = await db.execute(
        select(FundSnapshot)
        .where(FundSnapshot.fund_id == fund.id, FundSnapshot.tenant_id == tenant_id)
        .order_by(desc(FundSnapshot.report_date))
        .limit(1)
    )
    snap = result.scalar_one_or_none()
    if not snap:
        return None

    data = {"fund_name": fund.fund_name, "period": snap.period, "report_date": str(snap.report_date)}

    if metric == "aum":
        data.update({"aum_usd": snap.aum_usd, "aum_raw": snap.aum_raw})
    elif metric == "performance":
        data.update({
            "return_mtd": snap.return_mtd,
            "return_qtd": snap.return_qtd,
            "return_ytd": snap.return_ytd,
            "return_1yr": snap.return_1yr,
            "return_3yr": snap.return_3yr,
            "return_inception": snap.return_inception,
            "benchmark_name": snap.benchmark_name,
            "benchmark_return_1yr": snap.benchmark_return_1yr,
        })
    elif metric == "fees":
        data.update({
            "management_fee": snap.management_fee,
            "performance_fee": snap.performance_fee,
            "hurdle_rate": snap.hurdle_rate,
        })
    elif metric == "risk":
        data.update({
            "volatility": snap.volatility,
            "sharpe_ratio": snap.sharpe_ratio,
            "max_drawdown": snap.max_drawdown,
            "beta": snap.beta,
            "calmar_ratio": snap.calmar_ratio,
        })
    elif metric == "liquidity":
        data.update({
            "liquidity_terms": snap.liquidity_terms,
            "redemption_notice": snap.redemption_notice,
            "lockup_period": snap.lockup_period,
        })
    else:
        # Return everything
        data.update({
            "aum_raw": snap.aum_raw,
            "return_1yr": snap.return_1yr,
            "return_ytd": snap.return_ytd,
            "sharpe_ratio": snap.sharpe_ratio,
            "max_drawdown": snap.max_drawdown,
            "management_fee": snap.management_fee,
            "performance_fee": snap.performance_fee,
            "liquidity_terms": snap.liquidity_terms,
        })

    return data


async def query_personnel_changes(
    db: AsyncSession,
    fund_name: Optional[str],
    months: int = 12,
    tenant_id: uuid.UUID = DEFAULT_TENANT,
) -> Optional[dict]:
    """Get personnel changes timeline for a fund."""

    fund = await _get_fund(db, fund_name, tenant_id)
    if not fund:
        return None

    cutoff = date.today() - timedelta(days=months * 30)

    result = await db.execute(
        select(PersonnelChange)
        .where(
            PersonnelChange.fund_id == fund.id,
            PersonnelChange.tenant_id == tenant_id,
            PersonnelChange.effective_date >= cutoff,
        )
        .order_by(desc(PersonnelChange.effective_date))
    )
    changes = result.scalars().all()

    return {
        "fund_name": fund.fund_name,
        "period_months": months,
        "changes": [
            {
                "name": c.person_name,
                "previous_role": c.previous_role,
                "new_role": c.new_role,
                "change_type": c.change_type,
                "effective_date": str(c.effective_date) if c.effective_date else None,
                "notes": c.notes,
            }
            for c in changes
        ],
    }


async def query_qoq_sentiment(
    db: AsyncSession,
    fund_name: Optional[str],
    tenant_id: uuid.UUID = DEFAULT_TENANT,
) -> Optional[dict]:
    """Get last 4 quarters of performance for QoQ sentiment."""

    fund = await _get_fund(db, fund_name, tenant_id)
    if not fund:
        return None

    result = await db.execute(
        select(FundSnapshot)
        .where(FundSnapshot.fund_id == fund.id, FundSnapshot.tenant_id == tenant_id)
        .order_by(desc(FundSnapshot.report_date))
        .limit(8)
    )
    snaps = result.scalars().all()

    return {
        "fund_name": fund.fund_name,
        "history": [
            {
                "period": s.period,
                "return_qtd": s.return_qtd,
                "return_ytd": s.return_ytd,
                "aum_raw": s.aum_raw,
                "sharpe_ratio": s.sharpe_ratio,
            }
            for s in snaps
        ],
    }


async def _get_fund(db: AsyncSession, fund_name: Optional[str], tenant_id: uuid.UUID) -> Optional[Fund]:
    if not fund_name:
        # Return the most recently created fund
        result = await db.execute(
            select(Fund).where(Fund.tenant_id == tenant_id)
            .order_by(desc(Fund.created_at)).limit(1)
        )
        return result.scalar_one_or_none()

    # Fuzzy match on fund name
    result = await db.execute(
        select(Fund).where(
            Fund.tenant_id == tenant_id,
            Fund.fund_name.ilike(f"%{fund_name}%"),
        ).limit(1)
    )
    return result.scalar_one_or_none()
