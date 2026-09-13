"""Execute generated SQL against an isolated snapshot of authorized tables only."""
import threading
import duckdb


def query_authorized_tables(database: str, sql: str, allowed_tables: list[str], row_limit: int = 1000):
    # The generated query never receives a connection to the shared database.
    sandbox = duckdb.connect(':memory:', config={
        'enable_external_access': False, 'memory_limit': '256MB', 'threads': 2,
    })
    timer = None
    try:
        statements = sandbox.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError('Only one SELECT statement is allowed.')
        referenced = sandbox.get_table_names(sql)
        allowed = {name.lower(): name for name in allowed_tables}
        if not referenced or any(name.lower() not in allowed for name in referenced):
            raise ValueError('The query must use only datasets available to your role.')
        source = duckdb.connect(database, read_only=True)
        try:
            for index, name in enumerate(referenced):
                canonical = allowed[name.lower()]
                quoted = '"' + canonical.replace('"', '""') + '"'
                frame = source.execute(f'SELECT * FROM {quoted}').fetchdf()
                registered = f'_authorized_frame_{index}'
                sandbox.register(registered, frame)
                sandbox.execute(f'CREATE TABLE {quoted} AS SELECT * FROM {registered}')
                sandbox.unregister(registered)
        finally:
            source.close()
        timer = threading.Timer(10, sandbox.interrupt)
        timer.daemon = True
        timer.start()
        cursor = sandbox.execute(sql)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(row_limit + 1)
        return rows[:row_limit], columns, list(referenced), len(rows) > row_limit
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        sandbox.close()
