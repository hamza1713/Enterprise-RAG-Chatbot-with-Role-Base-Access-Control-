"""Offline regression tests. Uses temporary stores; never imports the AI engine."""
import os
import tempfile
from pathlib import Path

_temporary = tempfile.TemporaryDirectory(prefix='finsight-security-')
_root = Path(_temporary.name)
(_root / 'uploads').mkdir(parents=True, exist_ok=True)
os.environ.update(DB_NAME=str(_root / 'roles.db'), DUCKDB_NAME=str(_root / 'tables.duckdb'),
                  UPLOAD_DIR=str(_root / 'uploads'), JWT_SECRET='offline-test-signing-secret-32-characters', APP_ENV='development')

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import auth, documents, admin
from app.core.database import init_sqlite_schema, init_duckdb_schema, get_db_conn
from app.core.users import seed_default_users
from app.core.security import hash_password, verify_password
from app.core.sql_sandbox import query_authorized_tables

init_sqlite_schema()
init_duckdb_schema()
seed_default_users()
api = FastAPI()
for router in (auth.router, documents.router, admin.router):
    api.include_router(router)
client = TestClient(api)


def headers(username='admin', password='admin123'):
    response = client.get('/login', auth=(username, password))
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def test_regular_user_cannot_upload():
    response = client.post('/upload-docs', headers=headers('hr', 'hr123'),
                           data={'role': 'Finance'}, files={'file': ('forbidden.md', b'hello')})
    assert response.status_code == 403
    assert not list((_root / 'uploads').rglob('forbidden.md'))


def test_role_names_are_case_insensitively_unique():
    assert client.post('/create-role', headers=headers(), data={'role_name': 'hR'}).status_code == 409
    assert client.post('/create-role', headers=headers(), data={'role_name': '../bad'}).status_code == 400


def test_new_users_require_strong_password_and_keep_whitespace():
    args = {'username': 'test_member', 'role': 'HR', 'password': 'short'}
    assert client.post('/create-user', headers=headers(), data=args).status_code == 400
    args['password'] = ' long-test-password '
    assert client.post('/create-user', headers=headers(), data=args).status_code == 200
    assert client.get('/login', auth=('test_member', args['password'])).status_code == 200
    assert client.get('/login', auth=('test_member', args['password'].strip())).status_code == 401


@pytest.mark.parametrize('filename', ['../escape.md', '..\\escape.md', 'C:escape.md'])
def test_upload_rejects_path_traversal(filename):
    response = client.post('/upload-docs', headers=headers(), data={'role': 'HR'}, files={'file': (filename, b'hello')})
    assert response.status_code == 400


def test_upload_rejects_unknown_role():
    response = client.post('/upload-docs', headers=headers(), data={'role': '../../outside'}, files={'file': ('safe.md', b'hello')})
    assert response.status_code == 400


def test_upload_rejects_oversize_file():
    response = client.post('/upload-docs', headers=headers(), data={'role': 'HR'}, files={'file': ('large.md', b'x' * (20 * 1024 * 1024 + 1))})
    assert response.status_code == 413


def test_upload_rejects_empty_file():
    response = client.post('/upload-docs', headers=headers(), data={'role': 'HR'}, files={'file': ('empty.md', b'')})
    assert response.status_code == 400


def test_duplicate_upload_does_not_overwrite(monkeypatch):
    monkeypatch.setattr(documents, 'run_indexer', lambda: None)
    args = dict(headers=headers(), data={'role': 'HR'}, files={'file': ('safe.md', b'original')})
    assert client.post('/upload-docs', **args).status_code == 200
    args['files'] = {'file': ('safe.md', b'changed')}
    assert client.post('/upload-docs', **args).status_code == 409
    assert (_root / 'uploads' / 'HR' / 'safe.md').read_bytes() == b'original'


def test_pdf_requires_department_authorization():
    path = (_root / 'uploads' / 'private.pdf').resolve()
    path.write_bytes(b'%PDF-1.4 test')
    conn = get_db_conn()
    conn.execute('INSERT INTO documents (filename, role, filepath) VALUES (?,?,?)', ('private.pdf', 'Finance', str(path)))
    conn.commit(); conn.close()
    assert client.get('/preview-pdf', params={'filepath': str(path)}, headers=headers('hr', 'hr123')).status_code == 403
    allowed = client.get('/preview-pdf', params={'filepath': str(path)}, headers=headers('finance', 'finance123'))
    assert allowed.status_code == 200
    assert allowed.headers['cache-control'] == 'no-store'
    assert client.get('/preview-pdf', params={'filepath': str(path), 'token': headers()['Authorization'][7:]}).status_code in (401, 403)


def test_unregistered_pdf_is_denied_even_inside_uploads():
    path = _root / 'uploads' / 'unregistered.pdf'
    path.write_bytes(b'%PDF-1.4 test')
    assert client.get('/preview-pdf', params={'filepath': str(path)}, headers=headers()).status_code == 403


def test_registered_noncanonical_path_remains_accessible():
    directory = _root / 'uploads' / 'nested'
    directory.mkdir(exist_ok=True)
    actual = directory / 'alias.md'
    actual.write_text('Authorized content', encoding='utf-8')
    registered = str(directory / '..' / 'nested' / 'alias.md')
    conn = get_db_conn()
    conn.execute('INSERT INTO documents (filename, filepath, role) VALUES (?,?,?)', ('alias.md', registered, 'HR'))
    conn.commit(); conn.close()
    response = client.get('/documents/content', params={'filepath': registered}, headers=headers('hr', 'hr123'))
    assert response.status_code == 200 and response.json()['content'] == 'Authorized content'
    assert client.get('/documents/content', params={'filepath': registered}, headers=headers('finance', 'finance123')).status_code == 403


def test_changed_role_invalidates_old_token():
    token = headers('marketing', 'marketing123')
    conn = get_db_conn()
    conn.execute("UPDATE users SET role='General' WHERE username='marketing'")
    conn.commit(); conn.close()
    assert client.get('/documents', headers=token).status_code == 401


def test_seed_does_not_reset_existing_password():
    conn = get_db_conn()
    conn.execute('UPDATE users SET password=? WHERE username=?', (hash_password('updated-secret'), 'engineering'))
    conn.commit(); conn.close()
    seed_default_users()
    conn = get_db_conn()
    stored = conn.execute("SELECT password FROM users WHERE username='engineering'").fetchone()[0]
    conn.close()
    assert verify_password('updated-secret', stored)


@pytest.fixture
def sql_database(tmp_path):
    path = str(tmp_path / 'query.duckdb')
    conn = duckdb.connect(path)
    conn.execute('CREATE TABLE allowed AS SELECT 1 AS amount')
    conn.execute('CREATE TABLE private AS SELECT 999 AS amount')
    conn.close()
    return path


def test_authorized_sql_and_row_limit(sql_database):
    rows, columns, sources, truncated = query_authorized_tables(sql_database, 'SELECT * FROM allowed', ['allowed'])
    assert rows == [(1,)] and columns == ['amount'] and sources == ['allowed'] and not truncated
    rows, _, _, truncated = query_authorized_tables(sql_database, 'SELECT a.amount FROM allowed a CROSS JOIN range(20)', ['allowed'], row_limit=5)
    assert len(rows) == 5 and truncated


@pytest.mark.parametrize('sql', [
    'SELECT * FROM allowed, private',
    'SELECT * FROM allowed JOIN private ON true',
    'SELECT * FROM allowed WHERE EXISTS (SELECT 1 FROM private)',
    'SELECT * FROM allowed; SELECT * FROM private',
    'DELETE FROM allowed',
    "SELECT * FROM read_csv_auto('/private.csv')",
    "SELECT * FROM allowed, read_csv_auto('https://example.com/data.csv')",
])
def test_sql_cannot_escape_authorized_snapshot(sql_database, sql):
    with pytest.raises((ValueError, duckdb.Error)):
        query_authorized_tables(sql_database, sql, ['allowed'])
