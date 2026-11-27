"""
app/db/models.py — SQLAlchemy 2.0 ORM models for PostgreSQL 17 + pgvector/pgvectorscale.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import EMBEDDING_DIMENSIONS


class Base(DeclarativeBase):
    """Shared declarative base for FinSight ORM models."""


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("uq_roles_role_name_lower", func.lower(role_name), unique=True),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'local'")
    )
    oidc_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("uq_users_username_lower", func.lower(username), unique=True),
        Index("ix_users_role_name_lower", func.lower(role_name)),
        Index(
            "uq_users_provider_oidc_sub",
            auth_provider,
            oidc_sub,
            unique=True,
            postgresql_where=text("oidc_sub IS NOT NULL"),
        ),
    )


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    legacy_filepath: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'application/octet-stream'")
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers_str: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    embedded_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    dataset_tables: Mapped[list["DatasetTable"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_documents_role_filename_lower",
            func.lower(role),
            func.lower(filename),
            unique=True,
        ),
        Index("ix_documents_legacy_filepath", legacy_filepath),
        Index("ix_documents_role_lower", func.lower(role)),
        Index("ix_documents_embedded", embedded),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    doc_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'text'")
    )
    page_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    context_prefix: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(source, '') || ' ' || "
            "coalesce(section_title, '') || ' ' || content)",
            persisted=True,
        ),
    )
    embedding: Mapped[Any] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["DocumentRecord"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_document_chunks_doc_id", doc_id),
        Index("ix_document_chunks_role_lower", func.lower(role)),
        Index("ix_document_chunks_search_vector_gin", search_vector, postgresql_using="gin"),
    )


class DatasetTable(Base):
    __tablename__ = "dataset_tables"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    parquet_key: Mapped[str] = mapped_column(Text, nullable=False)
    columns_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["DocumentRecord"] = relationship(back_populates="dataset_tables")

    __table_args__ = (
        Index("uq_dataset_tables_name_lower", func.lower(table_name), unique=True),
        Index("ix_dataset_tables_role_lower", func.lower(role)),
        Index("ix_dataset_tables_doc_id", doc_id),
    )


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_doc_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'queued'")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    progress_current: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    progress_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "uq_jobs_active_idempotency",
            idempotency_key,
            unique=True,
            postgresql_where=text(
                "idempotency_key IS NOT NULL AND status IN ('queued', 'running', 'cancel_requested')"
            ),
        ),
        Index("ix_jobs_status", status),
        Index("ix_jobs_type_created", job_type, created_at),
        Index("ix_jobs_target_doc_id", target_doc_id),
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'queued'")
    )
    overall_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    per_role_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pass_fail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    rbac_overall: Mapped[str | None] = mapped_column(Text, nullable=True)
    rbac_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    records_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_evaluation_runs_created_at", created_at),
        Index("ix_evaluation_runs_status", status),
    )


class AclTuple(Base):
    __tablename__ = "acl_tuples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_acl_tuples_tuple",
            subject,
            relation,
            object_type,
            object_id,
            unique=True,
        ),
        Index("ix_acl_tuples_object", object_type, object_id, relation),
        Index("ix_acl_tuples_subject", subject),
    )


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'New Conversation'")
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list["ChatMessageRecord"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatMessageRecord.id",
    )

    __table_args__ = (
        Index("ix_chat_threads_user_updated", func.lower(username), updated_at),
    )


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    chart_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    agent_steps_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    thread: Mapped["ChatThread"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_chat_messages_thread_id_id", thread_id, id),)


class SemanticModel(Base):
    __tablename__ = "semantic_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    doc_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    metrics_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    dimensions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    synonyms_json: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    joins_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("uq_semantic_models_table_lower", func.lower(table_name), unique=True),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        nullable=False,
        unique=True,
        default=lambda: str(uuid.uuid4()),
    )
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    user_role: Mapped[str] = mapped_column(Text, nullable=False)
    auth_provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'local'")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorized_doc_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    authorized_dataset_names: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cited_doc_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cited_chunk_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    sql_executed: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    guardrail_flags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    outcome: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'allow'")
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_disclosure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_logs_created_at_desc", created_at.desc()),
        Index("ix_audit_logs_username_created", func.lower(username), created_at),
        Index("ix_audit_logs_event_outcome", event_type, outcome),
    )
