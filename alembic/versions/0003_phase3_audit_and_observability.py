"""Phase 3 append-only audit_logs table and Postgres immutability trigger.

Revision ID: 0003_phase3_audit_and_observability
Revises: 0002_phase2_rebac_threads_semantics
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase3_audit_and_observability"
down_revision: Union[str, Sequence[str], None] = "0002_phase2_rebac_threads_semantics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("user_role", sa.Text(), nullable=False),
        sa.Column(
            "auth_provider",
            sa.Text(),
            server_default=sa.text("'local'"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column(
            "authorized_doc_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "authorized_dataset_names",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cited_doc_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cited_chunk_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("sql_executed", sa.Text(), nullable=True),
        sa.Column(
            "sql_retries",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "guardrail_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Text(),
            server_default=sa.text("'allow'"),
            nullable=False,
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("prompt_sha256", sa.Text(), nullable=True),
        sa.Column("prompt_preview", sa.Text(), nullable=True),
        sa.Column(
            "ai_disclosure",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )

    op.execute(
        "CREATE INDEX ix_audit_logs_created_at_desc ON audit_logs (created_at DESC);"
    )
    op.execute(
        "CREATE INDEX ix_audit_logs_username_created ON audit_logs (LOWER(username), created_at);"
    )
    op.execute(
        "CREATE INDEX ix_audit_logs_event_outcome ON audit_logs (event_type, outcome);"
    )

    # Enforce append-only compliance immutability at the database engine layer.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only; UPDATE and DELETE operations are prohibited for compliance';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation();")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_event_outcome;")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_username_created;")
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_created_at_desc;")
    op.drop_table("audit_logs")
