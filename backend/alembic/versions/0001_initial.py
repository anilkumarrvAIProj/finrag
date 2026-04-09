"""Initial schema

Revision ID: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tenants
    op.create_table("tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("settings", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Users
    op.create_table("users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(255)),
        sa.Column("role", sa.String(32), nullable=False, server_default="read_only"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_tenant", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_tenant_external", "users", ["tenant_id", "external_id"])

    # Documents
    op.create_table("documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("doc_type", sa.String(32), server_default="other"),
        sa.Column("status", sa.String(32), server_default="uploaded"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_latest", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("s3_raw_key", sa.String(1024), nullable=False),
        sa.Column("s3_processed_key", sa.String(1024)),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("page_count", sa.Integer),
        sa.Column("fund_name", sa.String(512)),
        sa.Column("report_date", sa.DateTime(timezone=True)),
        sa.Column("is_scanned", sa.Boolean, server_default="false"),
        sa.Column("ocr_confidence", sa.Float),
        sa.Column("language", sa.String(10)),
        sa.Column("extracted_metadata", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True)),
        sa.Column("weaviate_namespace", sa.String(255)),
        sa.Column("chunk_count", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_docs_tenant", "documents", ["tenant_id"])
    op.create_index("ix_docs_hash_tenant", "documents", ["sha256_hash", "tenant_id"])
    op.create_index("ix_docs_status", "documents", ["status"])

    # Document Chunks
    op.create_table("document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("page_start", sa.Integer),
        sa.Column("page_end", sa.Integer),
        sa.Column("section_title", sa.String(512)),
        sa.Column("chunk_type", sa.String(32), server_default="text"),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("weaviate_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_document", "document_chunks", ["document_id"])
    op.create_index("ix_chunks_tenant", "document_chunks", ["tenant_id"])

    # Chat Sessions
    op.create_table("chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("doc_filter", postgresql.JSONB),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_user", "chat_sessions", ["user_id"])

    # Chat Messages — no tenant_id column
    op.create_table("chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", postgresql.JSONB),
        sa.Column("retrieval_metadata", postgresql.JSONB),
        sa.Column("web_search_used", sa.Boolean, server_default="false"),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_session", "chat_messages", ["session_id"])

    # Audit Logs
    op.create_table("audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("details", postgresql.JSONB),
        sa.Column("hmac_chain", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_tenant_time", "audit_logs", ["tenant_id", "created_at"])
    op.create_index("ix_audit_action", "audit_logs", ["action"])

    # RLS only on tables that have tenant_id
    rls_tables = ["documents", "document_chunks", "chat_sessions", "audit_logs", "users"]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        """)

    # Default tenant
    op.execute("""
        INSERT INTO tenants (id, name, slug)
        VALUES ('00000000-0000-0000-0000-000000000001', 'Default Tenant', 'default');
    """)

    # Default user for uploads
    op.execute("""
        INSERT INTO users (id, tenant_id, external_id, email, role)
        VALUES (
            '00000000-0000-0000-0000-000000000002',
            '00000000-0000-0000-0000-000000000001',
            'dev|default',
            'admin@finrag.local',
            'admin'
        );
    """)


def downgrade() -> None:
    for t in ["audit_logs", "chat_messages", "chat_sessions", "document_chunks", "documents", "users", "tenants"]:
        op.drop_table(t)
