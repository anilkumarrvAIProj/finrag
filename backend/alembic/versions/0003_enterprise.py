"""
Enterprise schema — Phase 1 & 2
- password_hash on users
- funds table
- fund_id on documents and chat_sessions
- quick_questions on tenants
- REGISTER and PASSWORD_CHANGE audit actions

Revision ID: 0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add password_hash to users
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))

    # 2. Add quick_questions to tenants
    op.add_column("tenants", sa.Column("quick_questions", postgresql.JSONB, nullable=True))

    # 3. Create funds table
    op.create_table("funds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("strategy", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("weaviate_collection", sa.String(255), nullable=True),
        sa.Column("quick_questions", postgresql.JSONB, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_funds_tenant", "funds", ["tenant_id"])
    op.create_unique_constraint("uq_funds_tenant_slug", "funds", ["tenant_id", "slug"])

    # 4. Add fund_id to documents
    op.add_column("documents",
        sa.Column("fund_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("funds.id"), nullable=True)
    )
    op.create_index("ix_documents_fund", "documents", ["fund_id"])

    # 5. Add fund_id to chat_sessions
    op.add_column("chat_sessions",
        sa.Column("fund_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("funds.id"), nullable=True)
    )

    # 6. Set password for default admin user
    # bcrypt hash of "FinRag@Admin123" — change immediately in production
    op.execute("""
        UPDATE users
        SET password_hash = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/Ler.L/bFfaFI9L.IC'
        WHERE email = 'admin@finrag.local'
    """)


def downgrade() -> None:
    op.drop_index("ix_documents_fund", "documents")
    op.drop_column("documents", "fund_id")
    op.drop_column("chat_sessions", "fund_id")
    op.drop_table("funds")
    op.drop_column("tenants", "quick_questions")
    op.drop_column("users", "password_hash")
