"""Phase 1 initial PostgreSQL 17 + pgvector/pgvectorscale schema.

Revision ID: 0001_phase1_postgres_pgvector
Revises:
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.core.config import EMBEDDING_DIMENSIONS

revision: str = "0001_phase1_postgres_pgvector"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    # vectorscale is present on timescale/timescaledb-ha:pg17 and skipped cleanly on plain pgvector images
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$;
        """
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_name", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("CREATE UNIQUE INDEX uq_roles_role_name_lower ON roles (LOWER(role_name));")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("CREATE UNIQUE INDEX uq_users_username_lower ON users (LOWER(username));")
    op.execute("CREATE INDEX ix_users_role_name_lower ON users (LOWER(role_name));")

    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("legacy_filepath", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), server_default=sa.text("'application/octet-stream'"), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("headers_str", sa.Text(), nullable=True),
        sa.Column("parser_used", sa.Text(), nullable=True),
        sa.Column("embedded", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_chunks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("embedded_chunks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.execute("CREATE UNIQUE INDEX uq_documents_role_filename_lower ON documents (LOWER(role), LOWER(filename));")
    op.create_index("ix_documents_legacy_filepath", "documents", ["legacy_filepath"], unique=False)
    op.execute("CREATE INDEX ix_documents_role_lower ON documents (LOWER(role));")
    op.create_index("ix_documents_embedded", "documents", ["embedded"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("chunk_type", sa.Text(), server_default=sa.text("'text'"), nullable=False),
        sa.Column("page_number", sa.Text(), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("context_prefix", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(source, '') || ' ' || coalesce(section_title, '') || ' ' || content)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id"),
    )
    op.create_index("ix_document_chunks_doc_id", "document_chunks", ["doc_id"], unique=False)
    op.execute("CREATE INDEX ix_document_chunks_role_lower ON document_chunks (LOWER(role));")
    op.execute("CREATE INDEX ix_document_chunks_search_vector_gin ON document_chunks USING gin (search_vector);")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vectorscale') THEN
                CREATE INDEX ix_document_chunks_embedding_ann
                    ON document_chunks USING diskann (embedding);
            ELSE
                CREATE INDEX ix_document_chunks_embedding_ann
                    ON document_chunks USING hnsw (embedding vector_cosine_ops);
            END IF;
        END $$;
        """
    )

    op.create_table(
        "dataset_tables",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("doc_id", sa.BigInteger(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("parquet_key", sa.Text(), nullable=False),
        sa.Column(
            "columns_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("CREATE UNIQUE INDEX uq_dataset_tables_name_lower ON dataset_tables (LOWER(table_name));")
    op.execute("CREATE INDEX ix_dataset_tables_role_lower ON dataset_tables (LOWER(role));")
    op.create_index("ix_dataset_tables_doc_id", "dataset_tables", ["doc_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("target_doc_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("progress_current", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("progress_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["target_doc_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_jobs_active_idempotency
            ON jobs (idempotency_key)
            WHERE idempotency_key IS NOT NULL
              AND status IN ('queued', 'running', 'cancel_requested');
        """
    )
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_type_created", "jobs", ["job_type", "created_at"], unique=False)
    op.create_index("ix_jobs_target_doc_id", "jobs", ["target_doc_id"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("overall_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("per_role_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pass_fail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rbac_overall", sa.Text(), nullable=True),
        sa.Column("rbac_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_object_key", sa.Text(), nullable=True),
        sa.Column("records_object_key", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_runs_created_at", "evaluation_runs", ["created_at"], unique=False)
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("evaluation_runs")
    op.drop_table("jobs")
    op.drop_table("dataset_tables")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("users")
    op.drop_table("roles")
