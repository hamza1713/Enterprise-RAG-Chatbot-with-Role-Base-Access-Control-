"""
tests/test_alembic_revisions.py — Offline guard on Alembic revision metadata.

Alembic's default `alembic_version.version_num` column is VARCHAR(32); a longer
revision id makes `alembic upgrade` fail after the migration body has run.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_VERSION_NUM_MAX = 32


def _scripts() -> ScriptDirectory:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_revision_ids_fit_alembic_version_column():
    too_long = [
        rev.revision
        for rev in _scripts().walk_revisions()
        if len(rev.revision) > _ALEMBIC_VERSION_NUM_MAX
    ]
    assert not too_long, f"Revision ids longer than {_ALEMBIC_VERSION_NUM_MAX} chars: {too_long}"


def test_single_linear_head():
    assert len(_scripts().get_heads()) == 1
