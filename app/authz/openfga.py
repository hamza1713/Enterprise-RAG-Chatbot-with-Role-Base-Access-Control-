"""
app/authz/openfga.py — OpenFGA (Zanzibar) ReBAC service with PostgreSQL `acl_tuples` mirror & fallback.

Enforces relationship-based access control across:
  - Roles & shared workspace folders (`role#assignee`, `folder#member`)
  - Per-document owners, departmental parent_role inheritance, C-Level admin_role, and direct viewer grants
  - Structured Parquet dataset inheritance from parent DocumentRecord
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import Any

from openfga_sdk.client import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import (
    ClientBatchCheckItem,
    ClientBatchCheckRequest,
    ClientListObjectsRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.models import (
    CreateStoreRequest,
    TypeDefinition,
    WriteAuthorizationModelRequest,
)
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import (
    OPENFGA_API_TOKEN,
    OPENFGA_API_URL,
    OPENFGA_MODEL_ID,
    OPENFGA_STORE_ID,
    OPENFGA_STORE_NAME,
)
from app.db.models import AclTuple, DatasetTable, DocumentRecord, User
from app.db.session import async_session, sync_session

logger = logging.getLogger("FinSight.authz")

# Canonical OpenFGA v1.1 Authorization Model for FinSight
FINSIGHT_FGA_MODEL_DICT: dict[str, Any] = {
    "schema_version": "1.1",
    "type_definitions": [
        {"type": "user"},
        {
            "type": "role",
            "relations": {"assignee": {"this": {}}},
            "metadata": {
                "relations": {
                    "assignee": {"directly_related_user_types": [{"type": "user"}]}
                }
            },
        },
        {
            "type": "folder",
            "relations": {"member": {"this": {}}},
            "metadata": {
                "relations": {
                    "member": {
                        "directly_related_user_types": [
                            {"type": "user"},
                            {"type": "role", "relation": "assignee"},
                        ]
                    }
                }
            },
        },
        {
            "type": "document",
            "relations": {
                "owner": {"this": {}},
                "admin_role": {"this": {}},
                "parent_role": {"this": {}},
                "parent_folder": {"this": {}},
                "viewer": {
                    "union": {
                        "child": [
                            {"this": {}},
                            {"computedUserset": {"relation": "owner"}},
                            {
                                "tupleToUserset": {
                                    "tupleset": {"relation": "parent_role"},
                                    "computedUserset": {"relation": "assignee"},
                                }
                            },
                            {
                                "tupleToUserset": {
                                    "tupleset": {"relation": "admin_role"},
                                    "computedUserset": {"relation": "assignee"},
                                }
                            },
                            {
                                "tupleToUserset": {
                                    "tupleset": {"relation": "parent_folder"},
                                    "computedUserset": {"relation": "member"},
                                }
                            },
                        ]
                    }
                },
            },
            "metadata": {
                "relations": {
                    "owner": {"directly_related_user_types": [{"type": "user"}]},
                    "admin_role": {"directly_related_user_types": [{"type": "role"}]},
                    "parent_role": {"directly_related_user_types": [{"type": "role"}]},
                    "parent_folder": {"directly_related_user_types": [{"type": "folder"}]},
                    "viewer": {
                        "directly_related_user_types": [
                            {"type": "user"},
                            {"type": "role", "relation": "assignee"},
                        ]
                    },
                }
            },
        },
        {
            "type": "dataset",
            "relations": {
                "owner": {"this": {}},
                "parent_doc": {"this": {}},
                "viewer": {
                    "union": {
                        "child": [
                            {"this": {}},
                            {"computedUserset": {"relation": "owner"}},
                            {
                                "tupleToUserset": {
                                    "tupleset": {"relation": "parent_doc"},
                                    "computedUserset": {"relation": "viewer"},
                                }
                            },
                        ]
                    }
                },
            },
            "metadata": {
                "relations": {
                    "owner": {"directly_related_user_types": [{"type": "user"}]},
                    "parent_doc": {"directly_related_user_types": [{"type": "document"}]},
                    "viewer": {
                        "directly_related_user_types": [
                            {"type": "user"},
                            {"type": "role", "relation": "assignee"},
                        ]
                    },
                }
            },
        },
    ],
}

_SAFE_SUBJECT_RE = re.compile(
    r"^(user:[a-z0-9_.-]+|role:[a-z0-9_-]+(?:#assignee)?|folder:[a-z0-9_-]+(?:#member)?|document:\d+)$"
)


def normalize_subject(raw_subject: str) -> str:
    """Validate and canonicalize an OpenFGA subject identifier (e.g. `user:alice`, `role:hr#assignee`)."""
    cleaned = (raw_subject or "").strip().lower()
    if ":" not in cleaned:
        raise ValueError("Subject must specify prefix (`user:<name>` or `role:<name>#assignee`).")
    if cleaned.startswith("role:") and "#" not in cleaned:
        cleaned = f"{cleaned}#assignee"
    if cleaned.startswith("folder:") and "#" not in cleaned:
        cleaned = f"{cleaned}#member"
    if not _SAFE_SUBJECT_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid ReBAC subject format: '{raw_subject}'")
    return cleaned


def _role_subject_for_tuple(role_name: str) -> str:
    return f"role:{(role_name or 'general').strip().lower()}"


def _user_subject(username: str) -> str:
    return f"user:{(username or '').strip().lower()}"


def _is_ignored_fga_tuple_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "already exists" in msg
        or "cannot write a tuple which already exists" in msg
        or "cannot delete a tuple which does not exist" in msg
    )


class ReBACService:
    """
    Unified OpenFGA ReBAC + PostgreSQL `acl_tuples` mirror service.

    When `OPENFGA_API_URL` is configured and reachable, authorization checks
    (`list_objects`, `batch_check`) hit OpenFGA directly. In offline unit tests or
    when OpenFGA is not configured, the exact same tuple graph evaluates cleanly
    against PostgreSQL `acl_tuples`.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_token: str | None = None,
        store_name: str | None = None,
        store_id: str | None = None,
        model_id: str | None = None,
    ):
        self.api_url = (OPENFGA_API_URL if api_url is None else api_url).strip().rstrip("/")
        self.api_token = (OPENFGA_API_TOKEN if api_token is None else api_token).strip()
        self.store_name = (store_name or OPENFGA_STORE_NAME or "finsight").strip()
        self._store_id: str | None = (store_id or OPENFGA_STORE_ID or "").strip() or None
        self._model_id: str | None = (model_id or OPENFGA_MODEL_ID or "").strip() or None
        self._init_lock: asyncio.Lock | None = None

    @property
    def openfga_enabled(self) -> bool:
        return bool(self.api_url)

    def _get_lock(self) -> asyncio.Lock:
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        return self._init_lock

    def _build_client_config(
        self,
        *,
        store_id: str | None = None,
        model_id: str | None = None,
    ) -> ClientConfiguration:
        creds = None
        if self.api_token:
            creds = Credentials(
                method="api_token",
                configuration=CredentialConfiguration(api_token=self.api_token),
            )
        return ClientConfiguration(
            api_url=self.api_url,
            store_id=store_id,
            authorization_model_id=model_id,
            credentials=creds,
            timeout_millisec=5000,
        )

    def _create_fga_client(
        self,
        *,
        store_id: str | None = None,
        model_id: str | None = None,
    ) -> OpenFgaClient:
        return OpenFgaClient(
            self._build_client_config(store_id=store_id, model_id=model_id)
        )

    async def aensure_store_and_model(self) -> tuple[str | None, str | None]:
        """Idempotently locate or create the OpenFGA store and write FinSight's v1.1 model."""
        if not self.openfga_enabled:
            return None, None
        if self._store_id and self._model_id:
            return self._store_id, self._model_id

        async with self._get_lock():
            if self._store_id and self._model_id:
                return self._store_id, self._model_id

            async with self._create_fga_client() as client:
                if not self._store_id:
                    stores_resp = await client.list_stores()
                    for st in getattr(stores_resp, "stores", []) or []:
                        if getattr(st, "name", "") == self.store_name:
                            self._store_id = st.id
                            break
                    if not self._store_id:
                        created = await client.create_store(
                            CreateStoreRequest(name=self.store_name)
                        )
                        self._store_id = created.id

            async with self._create_fga_client(store_id=self._store_id) as scoped:
                if not self._model_id:
                    models_resp = await scoped.read_authorization_models()
                    existing_models = getattr(models_resp, "authorization_models", []) or []
                    expected_types = {
                        td["type"] for td in FINSIGHT_FGA_MODEL_DICT["type_definitions"]
                    }
                    for candidate in existing_models:
                        cand_types = {
                            getattr(td, "type", "")
                            for td in (getattr(candidate, "type_definitions", []) or [])
                        }
                        if expected_types.issubset(cand_types):
                            self._model_id = candidate.id
                            break
                    if not self._model_id:
                        model_req = WriteAuthorizationModelRequest(
                            schema_version=FINSIGHT_FGA_MODEL_DICT["schema_version"],
                            type_definitions=[
                                TypeDefinition(**td)
                                for td in FINSIGHT_FGA_MODEL_DICT["type_definitions"]
                            ],
                        )
                        written = await scoped.write_authorization_model(model_req)
                        self._model_id = written.authorization_model_id

        return self._store_id, self._model_id

    async def _push_fga_mutations(
        self,
        *,
        writes: list[tuple[str, str, str, str]] | None = None,
        deletes: list[tuple[str, str, str, str]] | None = None,
    ) -> None:
        if not self.openfga_enabled:
            return
        writes = writes or []
        deletes = deletes or []
        if not writes and not deletes:
            return
        try:
            store_id, model_id = await self.aensure_store_and_model()
            if not store_id:
                return
            write_objs = [
                ClientTuple(user=s, relation=r, object=f"{ot}:{oid}")
                for s, r, ot, oid in writes
            ]
            delete_objs = [
                ClientTuple(user=s, relation=r, object=f"{ot}:{oid}")
                for s, r, ot, oid in deletes
            ]
            async with self._create_fga_client(store_id=store_id, model_id=model_id) as client:
                for w in write_objs:
                    try:
                        await client.write(ClientWriteRequest(writes=[w]))
                    except Exception as exc:
                        if not _is_ignored_fga_tuple_error(exc):
                            raise
                for d in delete_objs:
                    try:
                        await client.write(ClientWriteRequest(deletes=[d]))
                    except Exception as exc:
                        if not _is_ignored_fga_tuple_error(exc):
                            raise
        except Exception as exc:
            logger.warning(f"[OpenFGA] Tuple sync deferred ({type(exc).__name__}: {exc})")

    def _best_effort_sync_fga_push(
        self,
        *,
        writes: list[tuple[str, str, str, str]] | None = None,
        deletes: list[tuple[str, str, str, str]] | None = None,
    ) -> None:
        if not self.openfga_enabled:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._push_fga_mutations(writes=writes, deletes=deletes))
        except RuntimeError:
            try:
                asyncio.run(self._push_fga_mutations(writes=writes, deletes=deletes))
            except Exception as exc:
                logger.warning(f"[OpenFGA] Sync tuple push skipped: {exc}")

    # ── Postgres `acl_tuples` helpers (sync + async) ──────────────────────────

    @staticmethod
    def _upsert_tuples_sync(
        db: Session,
        tuples: list[tuple[str, str, str, str]],
        *,
        created_by: str | None = None,
    ) -> None:
        if not tuples:
            return
        rows = [
            {
                "subject": s,
                "relation": r,
                "object_type": ot,
                "object_id": oid,
                "created_by": created_by,
            }
            for s, r, ot, oid in tuples
        ]
        stmt = (
            pg_insert(AclTuple)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["subject", "relation", "object_type", "object_id"]
            )
        )
        db.execute(stmt)

    @staticmethod
    async def _upsert_tuples_async(
        db: AsyncSession,
        tuples: list[tuple[str, str, str, str]],
        *,
        created_by: str | None = None,
    ) -> None:
        if not tuples:
            return
        rows = [
            {
                "subject": s,
                "relation": r,
                "object_type": ot,
                "object_id": oid,
                "created_by": created_by,
            }
            for s, r, ot, oid in tuples
        ]
        stmt = (
            pg_insert(AclTuple)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["subject", "relation", "object_type", "object_id"]
            )
        )
        await db.execute(stmt)

    def sync_user_roles(
        self,
        db: Session,
        username: str,
        role_name: str,
        *,
        is_active: bool = True,
        created_by: str = "system",
    ) -> None:
        subj = _user_subject(username)
        existing = list(
            db.scalars(
                select(AclTuple).where(
                    AclTuple.subject == subj,
                    AclTuple.relation == "assignee",
                    AclTuple.object_type == "role",
                )
            )
        )
        deletes = [
            (row.subject, row.relation, row.object_type, row.object_id) for row in existing
        ]
        db.execute(
            delete(AclTuple).where(
                AclTuple.subject == subj,
                AclTuple.relation == "assignee",
                AclTuple.object_type == "role",
            )
        )
        writes: list[tuple[str, str, str, str]] = []
        if is_active:
            primary_role = (role_name or "general").strip().lower()
            writes.append((subj, "assignee", "role", primary_role))
            if primary_role != "general":
                writes.append((subj, "assignee", "role", "general"))
            self._upsert_tuples_sync(db, writes, created_by=created_by)
        self._best_effort_sync_fga_push(
            writes=writes, deletes=[d for d in deletes if d not in writes]
        )

    async def async_user_roles(
        self,
        db: AsyncSession,
        username: str,
        role_name: str,
        *,
        is_active: bool = True,
        previous_role: str | None = None,
        created_by: str = "system",
    ) -> None:
        subj = _user_subject(username)
        existing = list(
            await db.scalars(
                select(AclTuple).where(
                    AclTuple.subject == subj,
                    AclTuple.relation == "assignee",
                    AclTuple.object_type == "role",
                )
            )
        )
        deletes = [
            (row.subject, row.relation, row.object_type, row.object_id) for row in existing
        ]
        if previous_role:
            deletes.append((subj, "assignee", "role", previous_role.strip().lower()))
        await db.execute(
            delete(AclTuple).where(
                AclTuple.subject == subj,
                AclTuple.relation == "assignee",
                AclTuple.object_type == "role",
            )
        )
        writes: list[tuple[str, str, str, str]] = []
        if is_active:
            primary_role = (role_name or "general").strip().lower()
            writes.append((subj, "assignee", "role", primary_role))
            if primary_role != "general":
                writes.append((subj, "assignee", "role", "general"))
            await self._upsert_tuples_async(db, writes, created_by=created_by)
        await self._push_fga_mutations(
            writes=writes, deletes=[d for d in dict.fromkeys(deletes) if d not in writes]
        )

    def sync_document_tuples(
        self,
        db: Session,
        doc_id: int,
        role_name: str,
        *,
        owner_username: str | None = None,
        previous_role: str | None = None,
        created_by: str = "system",
    ) -> None:
        doc_id_str = str(int(doc_id))
        deletes: list[tuple[str, str, str, str]] = []
        if previous_role:
            old_role_subj = _role_subject_for_tuple(previous_role)
            db.execute(
                delete(AclTuple).where(
                    AclTuple.subject == old_role_subj,
                    AclTuple.relation == "parent_role",
                    AclTuple.object_type == "document",
                    AclTuple.object_id == doc_id_str,
                )
            )
            deletes.append((old_role_subj, "parent_role", "document", doc_id_str))

        writes: list[tuple[str, str, str, str]] = [
            (_role_subject_for_tuple(role_name), "parent_role", "document", doc_id_str),
            ("role:c-level", "admin_role", "document", doc_id_str),
        ]
        if owner_username:
            writes.append((_user_subject(owner_username), "owner", "document", doc_id_str))
        self._upsert_tuples_sync(db, writes, created_by=created_by)
        self._best_effort_sync_fga_push(writes=writes, deletes=deletes)

    async def async_document_tuples(
        self,
        db: AsyncSession,
        doc_id: int,
        role_name: str,
        *,
        owner_username: str | None = None,
        previous_role: str | None = None,
        created_by: str = "system",
    ) -> None:
        doc_id_str = str(int(doc_id))
        deletes: list[tuple[str, str, str, str]] = []
        if previous_role and previous_role.strip().lower() != role_name.strip().lower():
            old_subj = _role_subject_for_tuple(previous_role)
            await db.execute(
                delete(AclTuple).where(
                    AclTuple.subject == old_subj,
                    AclTuple.relation == "parent_role",
                    AclTuple.object_type == "document",
                    AclTuple.object_id == doc_id_str,
                )
            )
            deletes.append((old_subj, "parent_role", "document", doc_id_str))

        writes: list[tuple[str, str, str, str]] = [
            (_role_subject_for_tuple(role_name), "parent_role", "document", doc_id_str),
            ("role:c-level", "admin_role", "document", doc_id_str),
        ]
        if owner_username:
            writes.append((_user_subject(owner_username), "owner", "document", doc_id_str))
        await self._upsert_tuples_async(db, writes, created_by=created_by)
        await self._push_fga_mutations(writes=writes, deletes=deletes)

    def sync_dataset_tuples(
        self,
        db: Session,
        doc_id: int,
        table_name: str,
        *,
        owner_username: str | None = None,
        created_by: str = "system",
    ) -> None:
        ds_id = table_name.strip().lower()
        writes = [(f"document:{int(doc_id)}", "parent_doc", "dataset", ds_id)]
        if owner_username:
            writes.append((_user_subject(owner_username), "owner", "dataset", ds_id))
        self._upsert_tuples_sync(db, writes, created_by=created_by)
        self._best_effort_sync_fga_push(writes=writes)

    async def async_dataset_tuples(
        self,
        db: AsyncSession,
        doc_id: int,
        table_name: str,
        *,
        owner_username: str | None = None,
        created_by: str = "system",
    ) -> None:
        ds_id = table_name.strip().lower()
        writes = [(f"document:{int(doc_id)}", "parent_doc", "dataset", ds_id)]
        if owner_username:
            writes.append((_user_subject(owner_username), "owner", "dataset", ds_id))
        await self._upsert_tuples_async(db, writes, created_by=created_by)
        await self._push_fga_mutations(writes=writes)

    async def adelete_document_tuples(
        self,
        db: AsyncSession,
        doc_id: int,
        dataset_names: list[str] | None = None,
    ) -> None:
        doc_id_str = str(int(doc_id))
        doc_rows = list(
            await db.scalars(
                select(AclTuple).where(
                    AclTuple.object_type == "document",
                    AclTuple.object_id == doc_id_str,
                )
            )
        )
        ds_ids = [name.strip().lower() for name in (dataset_names or [])]
        ds_rows: list[AclTuple] = []
        if ds_ids:
            ds_rows = list(
                await db.scalars(
                    select(AclTuple).where(
                        AclTuple.object_type == "dataset",
                        AclTuple.object_id.in_(ds_ids),
                    )
                )
            )
        deletes = [
            (r.subject, r.relation, r.object_type, r.object_id) for r in (*doc_rows, *ds_rows)
        ]
        await db.execute(
            delete(AclTuple).where(
                AclTuple.object_type == "document",
                AclTuple.object_id == doc_id_str,
            )
        )
        if ds_ids:
            await db.execute(
                delete(AclTuple).where(
                    AclTuple.object_type == "dataset",
                    AclTuple.object_id.in_(ds_ids),
                )
            )
        await self._push_fga_mutations(deletes=deletes)

    async def agrant_permission(
        self,
        db: AsyncSession,
        *,
        subject: str,
        relation: str,
        object_type: str,
        object_id: str,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        clean_subject = normalize_subject(subject)
        clean_rel = (relation or "viewer").strip().lower()
        if clean_rel not in {"viewer", "owner", "parent_folder"}:
            raise ValueError(f"Unsupported ReBAC grant relation: '{relation}'")
        clean_type = object_type.strip().lower()
        clean_oid = str(object_id).strip().lower()

        await self._upsert_tuples_async(
            db,
            [(clean_subject, clean_rel, clean_type, clean_oid)],
            created_by=created_by,
        )
        await self._push_fga_mutations(
            writes=[(clean_subject, clean_rel, clean_type, clean_oid)]
        )
        return {
            "subject": clean_subject,
            "relation": clean_rel,
            "object_type": clean_type,
            "object_id": clean_oid,
        }

    async def arevoke_permission(
        self,
        db: AsyncSession,
        *,
        subject: str,
        relation: str,
        object_type: str,
        object_id: str,
    ) -> bool:
        clean_subject = normalize_subject(subject)
        clean_rel = (relation or "viewer").strip().lower()
        clean_type = object_type.strip().lower()
        clean_oid = str(object_id).strip().lower()

        res = await db.execute(
            delete(AclTuple).where(
                AclTuple.subject == clean_subject,
                AclTuple.relation == clean_rel,
                AclTuple.object_type == clean_type,
                AclTuple.object_id == clean_oid,
            )
        )
        await self._push_fga_mutations(
            deletes=[(clean_subject, clean_rel, clean_type, clean_oid)]
        )
        return bool(res.rowcount and res.rowcount > 0)

    async def alist_document_permissions(
        self,
        db: AsyncSession,
        doc_id: int,
    ) -> list[dict[str, Any]]:
        rows = list(
            await db.scalars(
                select(AclTuple)
                .where(
                    AclTuple.object_type == "document",
                    AclTuple.object_id == str(int(doc_id)),
                )
                .order_by(AclTuple.id.asc())
            )
        )
        return [
            {
                "id": r.id,
                "subject": r.subject,
                "relation": r.relation,
                "object_type": r.object_type,
                "object_id": r.object_id,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def async_all_to_openfga(self) -> int:
        """Reconcile Postgres users/documents/datasets & acl_tuples into OpenFGA at startup."""
        if not self.openfga_enabled:
            return 0
        try:
            store_id, model_id = await self.aensure_store_and_model()
            if not store_id:
                return 0
            async with async_session() as db:
                users = list(await db.scalars(select(User)))
                for u in users:
                    primary = (u.role_name or "general").strip().lower()
                    u_subj = _user_subject(u.username)
                    if u.is_active:
                        rows = [(u_subj, "assignee", "role", primary)]
                        if primary != "general":
                            rows.append((u_subj, "assignee", "role", "general"))
                        await self._upsert_tuples_async(db, rows, created_by="startup_sync")
                docs = list(await db.scalars(select(DocumentRecord)))
                for doc in docs:
                    await self._upsert_tuples_async(
                        db,
                        [
                            (
                                _role_subject_for_tuple(doc.role),
                                "parent_role",
                                "document",
                                str(doc.id),
                            ),
                            ("role:c-level", "admin_role", "document", str(doc.id)),
                        ],
                        created_by="startup_sync",
                    )
                datasets = list(await db.scalars(select(DatasetTable)))
                for ds in datasets:
                    await self._upsert_tuples_async(
                        db,
                        [
                            (
                                f"document:{int(ds.doc_id)}",
                                "parent_doc",
                                "dataset",
                                ds.table_name.strip().lower(),
                            )
                        ],
                        created_by="startup_sync",
                    )
                await db.commit()
                all_tuples = list(await db.scalars(select(AclTuple)))

            writes = [
                (t.subject, t.relation, t.object_type, t.object_id) for t in all_tuples
            ]
            await self._push_fga_mutations(writes=writes)
            return len(writes)
        except Exception as exc:
            logger.warning(f"[OpenFGA] Startup reconciliation skipped: {exc}")
            return 0

    # ── Authorization Graph Evaluation (OpenFGA HTTP -> PG Fallback) ──────────

    async def _fga_list_objects(self, username: str, object_type: str) -> list[str] | None:
        if not self.openfga_enabled:
            return None
        try:
            store_id, model_id = await self.aensure_store_and_model()
            if not store_id:
                return None
            async with self._create_fga_client(store_id=store_id, model_id=model_id) as client:
                req = ClientListObjectsRequest(
                    user=_user_subject(username),
                    relation="viewer",
                    type=object_type,
                )
                resp = await client.list_objects(req)
                prefix = f"{object_type}:"
                return [
                    obj[len(prefix) :]
                    for obj in (getattr(resp, "objects", []) or [])
                    if isinstance(obj, str) and obj.startswith(prefix)
                ]
        except Exception as exc:
            logger.warning(
                f"[OpenFGA] list_objects({object_type}) failed ({type(exc).__name__}); "
                "falling back to Postgres ReBAC mirror."
            )
            return None

    async def _fga_batch_check(
        self, username: str, object_type: str, object_ids: list[str]
    ) -> set[str] | None:
        if not self.openfga_enabled or not object_ids:
            return None
        try:
            store_id, model_id = await self.aensure_store_and_model()
            if not store_id:
                return None
            user_str = _user_subject(username)
            checks = [
                ClientBatchCheckItem(
                    user=user_str,
                    relation="viewer",
                    object=f"{object_type}:{oid}",
                    correlation_id=str(idx),
                )
                for idx, oid in enumerate(object_ids)
            ]
            id_by_corr = {str(idx): oid for idx, oid in enumerate(object_ids)}
            async with self._create_fga_client(store_id=store_id, model_id=model_id) as client:
                resp = await client.batch_check(ClientBatchCheckRequest(checks=checks))
                allowed: set[str] = set()
                for item in getattr(resp, "result", []) or []:
                    if getattr(item, "allowed", False):
                        corr = getattr(item, "correlation_id", None)
                        if corr in id_by_corr:
                            allowed.add(id_by_corr[corr])
                return allowed
        except Exception as exc:
            logger.warning(
                f"[OpenFGA] batch_check({object_type}) failed ({type(exc).__name__}); "
                "falling back to Postgres ReBAC mirror."
            )
            return None

    @staticmethod
    def _eval_pg_authorized_doc_ids_rows(
        username: str,
        user_role: str,
        tuples: list[AclTuple],
        all_docs: list[tuple[int, str]],
    ) -> list[int]:
        """
        Pure deterministic Zanzibar evaluator matching `FINSIGHT_FGA_MODEL_DICT`.
        Falls back safely to baseline `DocumentRecord.role` only for documents that
        have no `parent_role` tuple yet (e.g., direct test fixture inserts).
        """
        user_subj = _user_subject(username)
        primary_role = (user_role or "general").strip().lower()

        user_roles: set[str] = {primary_role, "general"} if primary_role else {"general"}
        user_folders: set[str] = set()
        for t in tuples:
            if (
                t.subject == user_subj
                and t.relation == "assignee"
                and t.object_type == "role"
            ):
                user_roles.add(t.object_id.lower())
        role_assignee_subjs = {f"role:{r}#assignee" for r in user_roles}

        for t in tuples:
            if t.relation == "member" and t.object_type == "folder":
                if t.subject == user_subj or t.subject in role_assignee_subjs:
                    user_folders.add(t.object_id.lower())
        folder_member_subjs = {f"folder:{f}#member" for f in user_folders}

        doc_parent_roles: set[str] = set()
        allowed_doc_ids: set[int] = set()
        for t in tuples:
            if t.object_type != "document":
                continue
            try:
                did = int(t.object_id)
            except ValueError:
                continue
            if t.relation == "parent_role":
                doc_parent_roles.add(t.object_id)
                role_id = t.subject.removeprefix("role:").lower()
                if role_id in user_roles:
                    allowed_doc_ids.add(did)
            elif t.relation == "admin_role":
                role_id = t.subject.removeprefix("role:").lower()
                if role_id in user_roles:
                    allowed_doc_ids.add(did)
            elif t.relation in {"owner", "viewer"}:
                if t.subject == user_subj or t.subject in role_assignee_subjs:
                    allowed_doc_ids.add(did)
            elif t.relation == "parent_folder":
                folder_id = t.subject.removeprefix("folder:").lower()
                if folder_id in user_folders or f"{t.subject}#member" in folder_member_subjs:
                    allowed_doc_ids.add(did)

        # Compatibility guard for raw ORM fixture rows lacking acl_tuples entries
        for doc_id, doc_role in all_docs:
            if str(doc_id) not in doc_parent_roles:
                rlow = (doc_role or "general").strip().lower()
                if "c-level" in user_roles or rlow in user_roles:
                    allowed_doc_ids.add(int(doc_id))

        return sorted(allowed_doc_ids)

    async def alist_authorized_doc_ids(
        self,
        db: AsyncSession | None = None,
        *,
        username: str,
        user_role: str,
    ) -> list[int]:
        fga_ids = await self._fga_list_objects(username, "document")
        if fga_ids is not None:
            parsed: set[int] = set()
            for item in fga_ids:
                try:
                    parsed.add(int(item))
                except ValueError:
                    continue
            return sorted(parsed)

        async def _eval(session: AsyncSession) -> list[int]:
            tuples = list(await session.scalars(select(AclTuple)))
            all_docs = [
                (int(r[0]), str(r[1]))
                for r in (
                    await session.execute(select(DocumentRecord.id, DocumentRecord.role))
                ).all()
            ]
            return self._eval_pg_authorized_doc_ids_rows(username, user_role, tuples, all_docs)

        if db is not None:
            return await _eval(db)
        async with async_session() as session:
            return await _eval(session)

    async def abatch_filter_doc_ids(
        self,
        db: AsyncSession | None = None,
        *,
        username: str,
        user_role: str,
        candidate_doc_ids: list[int],
    ) -> set[int]:
        unique_ids = sorted({int(d) for d in candidate_doc_ids})
        if not unique_ids:
            return set()
        fga_allowed = await self._fga_batch_check(
            username, "document", [str(d) for d in unique_ids]
        )
        if fga_allowed is not None:
            return {int(x) for x in fga_allowed if x.isdigit()}
        allowed_list = await self.alist_authorized_doc_ids(
            db, username=username, user_role=user_role
        )
        return set(allowed_list).intersection(unique_ids)

    async def acheck_document_access(
        self,
        db: AsyncSession,
        *,
        username: str,
        user_role: str,
        doc_id: int,
    ) -> bool:
        allowed = await self.abatch_filter_doc_ids(
            db, username=username, user_role=user_role, candidate_doc_ids=[doc_id]
        )
        return int(doc_id) in allowed

    async def alist_authorized_datasets(
        self,
        db: AsyncSession | None = None,
        *,
        username: str,
        user_role: str,
    ) -> list[dict[str, Any]]:
        allowed_doc_ids = set(
            await self.alist_authorized_doc_ids(db, username=username, user_role=user_role)
        )
        fga_ds = await self._fga_list_objects(username, "dataset")
        fga_ds_set = {x.lower() for x in fga_ds} if fga_ds is not None else None

        async def _fetch(session: AsyncSession) -> list[dict[str, Any]]:
            stmt = (
                select(
                    DatasetTable.doc_id,
                    DatasetTable.table_name,
                    DatasetTable.parquet_key,
                    DatasetTable.columns_json,
                    DatasetTable.role,
                    DocumentRecord.filename,
                )
                .join(DocumentRecord, DatasetTable.doc_id == DocumentRecord.id)
                .order_by(DatasetTable.table_name.asc())
            )
            rows = (await session.execute(stmt)).all()
            out: list[dict[str, Any]] = []
            for row in rows:
                doc_id = int(row[0])
                tname = str(row[1])
                if fga_ds_set is not None:
                    if tname.lower() not in fga_ds_set and doc_id not in allowed_doc_ids:
                        continue
                elif doc_id not in allowed_doc_ids:
                    continue
                out.append(
                    {
                        "doc_id": doc_id,
                        "table_name": tname,
                        "parquet_key": row[2],
                        "columns": list(row[3] or []),
                        "role": row[4],
                        "filename": row[5],
                    }
                )
            return out

        if db is not None:
            return await _fetch(db)
        async with async_session() as session:
            return await _fetch(session)

    def list_authorized_doc_ids_sync(
        self,
        db: Session | None = None,
        *,
        username: str,
        user_role: str,
    ) -> list[int]:
        if self.openfga_enabled:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(
                    self.alist_authorized_doc_ids(None, username=username, user_role=user_role)
                )

        def _eval(session: Session) -> list[int]:
            tuples = list(session.scalars(select(AclTuple)))
            all_docs = [
                (int(r[0]), str(r[1]))
                for r in session.execute(select(DocumentRecord.id, DocumentRecord.role)).all()
            ]
            return self._eval_pg_authorized_doc_ids_rows(username, user_role, tuples, all_docs)

        if db is not None:
            return _eval(db)
        with sync_session() as session:
            return _eval(session)

    def list_authorized_datasets_sync(
        self,
        db: Session | None = None,
        *,
        username: str,
        user_role: str,
    ) -> list[dict[str, Any]]:
        def _fetch(session: Session) -> list[dict[str, Any]]:
            allowed_docs = set(
                self.list_authorized_doc_ids_sync(
                    session, username=username, user_role=user_role
                )
            )
            stmt = (
                select(
                    DatasetTable.doc_id,
                    DatasetTable.table_name,
                    DatasetTable.parquet_key,
                    DatasetTable.columns_json,
                    DatasetTable.role,
                    DocumentRecord.filename,
                )
                .join(DocumentRecord, DatasetTable.doc_id == DocumentRecord.id)
                .order_by(DatasetTable.table_name.asc())
            )
            out: list[dict[str, Any]] = []
            for row in session.execute(stmt).all():
                if int(row[0]) in allowed_docs:
                    out.append(
                        {
                            "doc_id": int(row[0]),
                            "table_name": str(row[1]),
                            "parquet_key": row[2],
                            "columns": list(row[3] or []),
                            "role": row[4],
                            "filename": row[5],
                        }
                    )
            return out

        if db is not None:
            return _fetch(db)
        with sync_session() as session:
            return _fetch(session)


_rebac_lock = threading.Lock()
_rebac_service: ReBACService | None = None


def get_rebac_service() -> ReBACService:
    global _rebac_service
    if _rebac_service is None:
        with _rebac_lock:
            if _rebac_service is None:
                _rebac_service = ReBACService()
    return _rebac_service
