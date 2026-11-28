"""Phase 2 ReBAC ACL tuples, OIDC identity columns, persistent threads, and semantic models.

Revision ID: 0002_phase2_rebac_threads
Revises: 0001_phase1_postgres_pgvector
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase2_rebac_threads"
down_revision: Union[str, Sequence[str], None] = "0001_phase1_postgres_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.Text(),
            server_default=sa.text("'local'"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("oidc_sub", sa.Text(), nullable=True))
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_provider_oidc_sub
            ON users (auth_provider, oidc_sub)
            WHERE oidc_sub IS NOT NULL;
        """
    )

    op.create_table(
        "acl_tuples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_acl_tuples_tuple",
        "acl_tuples",
        ["subject", "relation", "object_type", "object_id"],
        unique=True,
    )
    op.create_index(
        "ix_acl_tuples_object",
        "acl_tuples",
        ["object_type", "object_id", "relation"],
        unique=False,
    )
    op.create_index("ix_acl_tuples_subject", "acl_tuples", ["subject"], unique=False)

    op.create_table(
        "chat_threads",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column(
            "title",
            sa.Text(),
            server_default=sa.text("'New Conversation'"),
            nullable=False,
        ),
        sa.Column(
            "archived",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX ix_chat_threads_user_updated ON chat_threads (LOWER(username), updated_at);"
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=True),
        sa.Column("sql_query", sa.Text(), nullable=True),
        sa.Column(
            "chart_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "citations_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "agent_steps_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["chat_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_thread_id_id",
        "chat_messages",
        ["thread_id", "id"],
        unique=False,
    )

    op.create_table(
        "semantic_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.BigInteger(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "dimensions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "synonyms_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "joins_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_semantic_models_table_lower ON semantic_models (LOWER(table_name));"
    )

    # Backfill ReBAC baseline tuples from Phase 1 users, documents, and dataset tables.
    op.execute(
        """
        INSERT INTO acl_tuples (subject, relation, object_type, object_id, created_by)
        SELECT 'user:' || LOWER(username), 'assignee', 'role', LOWER(role_name), 'migration_0002'
        FROM users
        WHERE is_active = true
        ON CONFLICT (subject, relation, object_type, object_id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO acl_tuples (subject, relation, object_type, object_id, created_by)
        SELECT 'user:' || LOWER(username), 'assignee', 'role', 'general', 'migration_0002'
        FROM users
        WHERE is_active = true AND LOWER(role_name) <> 'general'
        ON CONFLICT (subject, relation, object_type, object_id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO acl_tuples (subject, relation, object_type, object_id, created_by)
        SELECT 'role:' || LOWER(role), 'parent_role', 'document', id::text, 'migration_0002'
        FROM documents
        ON CONFLICT (subject, relation, object_type, object_id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO acl_tuples (subject, relation, object_type, object_id, created_by)
        SELECT 'role:c-level', 'admin_role', 'document', id::text, 'migration_0002'
        FROM documents
        ON CONFLICT (subject, relation, object_type, object_id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO acl_tuples (subject, relation, object_type, object_id, created_by)
        SELECT 'document:' || doc_id::text, 'parent_doc', 'dataset', LOWER(table_name), 'migration_0002'
        FROM dataset_tables
        ON CONFLICT (subject, relation, object_type, object_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_semantic_models_table_lower;")
    op.drop_table("semantic_models")

    op.drop_index("ix_chat_messages_thread_id_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.execute("DROP INDEX IF EXISTS ix_chat_threads_user_updated;")
    op.drop_table("chat_threads")

    op.drop_index("ix_acl_tuples_subject", table_name="acl_tuples")
    op.drop_index("ix_acl_tuples_object", table_name="acl_tuples")
    op.drop_index("uq_acl_tuples_tuple", table_name="acl_tuples")
    op.drop_table("acl_tuples")

    op.execute("DROP INDEX IF EXISTS uq_users_provider_oidc_sub;")
    op.drop_column("users", "oidc_sub")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "email")
