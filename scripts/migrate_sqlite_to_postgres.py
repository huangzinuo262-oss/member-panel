from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from config import DB_PATH, DATABASE_URL

if not DATABASE_URL:
    raise SystemExit('缺少 DATABASE_URL，无法迁移到 Postgres')

try:
    import psycopg
except Exception as exc:  # pragma: no cover
    raise SystemExit(f'psycopg 不可用: {exc}')

BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_PATH = Path(os.environ.get('SQLITE_PATH', str(DB_PATH))).resolve()
TABLES = [
    'users',
    'sessions',
    'members',
    'renewals',
    'audit_logs',
]


def normalize_database_url(url: str) -> str:
    if url.startswith('postgres://'):
        return 'postgresql://' + url[len('postgres://'):]
    return url


def table_exists_sqlite(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def fetch_rows_sqlite(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    cur = conn.execute(f'SELECT * FROM {table}')
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return columns, rows


def truncate_postgres(conn) -> None:
    conn.execute(
        'TRUNCATE TABLE audit_logs, renewals, members, sessions, users RESTART IDENTITY CASCADE'
    )


def copy_table(pg_conn, table: str, columns: list[str], rows: list[tuple]) -> None:
    if not rows:
        print(f'[skip] {table}: 0 rows')
        return
    quoted = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))
    sql = f'INSERT INTO {table} ({quoted}) VALUES ({placeholders})'
    with pg_conn.cursor() as cur:
        cur.executemany(sql, rows)
    print(f'[ok] {table}: {len(rows)} rows')


def reset_sequences(pg_conn) -> None:
    sql = '''
    SELECT setval(
        pg_get_serial_sequence(%s, 'id'),
        COALESCE((SELECT MAX(id) FROM {}), 1),
        (SELECT COUNT(*) > 0 FROM {})
    )
    '''
    for table in TABLES:
        with pg_conn.cursor() as cur:
            cur.execute(sql.format(table, table), (table,))


def main() -> None:
    if not SQLITE_PATH.exists():
        raise SystemExit(f'SQLite 文件不存在: {SQLITE_PATH}')

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    try:
        pg_conn = psycopg.connect(normalize_database_url(DATABASE_URL))
        try:
            with pg_conn:
                truncate_postgres(pg_conn)
                for table in TABLES:
                    if not table_exists_sqlite(sqlite_conn, table):
                        print(f'[skip] {table}: sqlite table missing')
                        continue
                    columns, rows = fetch_rows_sqlite(sqlite_conn, table)
                    copy_table(pg_conn, table, columns, rows)
                reset_sequences(pg_conn)
            print('迁移完成')
        finally:
            pg_conn.close()
    finally:
        sqlite_conn.close()


if __name__ == '__main__':
    main()
