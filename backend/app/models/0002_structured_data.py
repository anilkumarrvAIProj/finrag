"""Structured financial data tables

Revision ID: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("funds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fund_name", sa.String(255), nullable=False),
        sa.Column("manager_name", sa.String(255)),
        sa.Column("strategy", sa.String(255)),
        sa.Column("inception_date", sa.Date),
        sa.Column("domicile", sa.String(100)),
        sa.Column("currency", sa.String(10)),
        sa.Column("weaviate_namespace", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_funds_tenant", "funds", ["tenant_id"])
    op.create_index("ix_funds_name", "funds", ["fund_name"])

    op.create_table("fund_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("report_date", sa.Date),
        sa.Column("period", sa.String(20)),
        sa.Column("aum_usd", sa.Float), sa.Column("aum_raw", sa.String(50)),
        sa.Column("return_mtd", sa.Float), sa.Column("return_qtd", sa.Float),
        sa.Column("return_ytd", sa.Float), sa.Column("return_1yr", sa.Float),
        sa.Column("return_3yr", sa.Float), sa.Column("return_5yr", sa.Float),
        sa.Column("return_inception", sa.Float),
        sa.Column("volatility", sa.Float), sa.Column("sharpe_ratio", sa.Float),
        sa.Column("max_drawdown", sa.Float), sa.Column("beta", sa.Float),
        sa.Column("calmar_ratio", sa.Float),
        sa.Column("management_fee", sa.Float), sa.Column("performance_fee", sa.Float),
        sa.Column("hurdle_rate", sa.Float), sa.Column("liquidity_terms", sa.String(255)),
        sa.Column("lockup_period", sa.String(100)), sa.Column("redemption_notice", sa.String(100)),
        sa.Column("benchmark_name", sa.String(100)), sa.Column("benchmark_return_1yr", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_snapshots_fund", "fund_snapshots", ["fund_id"])
    op.create_index("ix_snapshots_date", "fund_snapshots", ["report_date"])

    op.create_table("fund_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("report_date", sa.Date),
        sa.Column("period", sa.String(20)),
        sa.Column("position_name", sa.String(255), nullable=False),
        sa.Column("ticker", sa.String(20)),
        sa.Column("sector", sa.String(100)),
        sa.Column("asset_class", sa.String(100)),
        sa.Column("direction", sa.String(10)),
        sa.Column("weight_pct", sa.Float),
        sa.Column("rank", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_positions_fund_date", "fund_positions", ["fund_id", "report_date"])

    op.create_table("personnel_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_name", sa.String(255), nullable=False),
        sa.Column("previous_role", sa.String(255)),
        sa.Column("new_role", sa.String(255)),
        sa.Column("change_type", sa.String(50)),
        sa.Column("effective_date", sa.Date),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_personnel_fund", "personnel_changes", ["fund_id"])



    op.create_table("fund_raw_data",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("funds.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=False),
        sa.Column("data", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_raw_data_fund", "fund_raw_data", ["fund_id"])


def downgrade() -> None:
    for t in ["fund_raw_data", "personnel_changes", "fund_positions", "fund_snapshots", "funds"]:
        op.drop_table(t)
