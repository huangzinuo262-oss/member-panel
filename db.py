import hashlib
import hmac
import os
import secrets
import sqlite3
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from config import DB_BACKEND, DB_PATH, DATABASE_URL

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency for sqlite-only mode
    psycopg = None
    dict_row = None

PBKDF2_ROUNDS = 120_000
SESSION_DAYS = 30
IS_POSTGRES = DB_BACKEND == 'postgres'


def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _normalize_database_url(url: str) -> str:
    if url.startswith('postgres://'):
        return 'postgresql://' + url[len('postgres://'):]
    return url


@contextmanager
def get_conn():
    if IS_POSTGRES:
        if psycopg is None:
            raise RuntimeError('DATABASE_URL 已配置为 Postgres，但 psycopg 未安装')
        conn = psycopg.connect(_normalize_database_url(DATABASE_URL), row_factory=dict_row)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = dict_factory
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def run(conn, sql: str, params: tuple[Any, ...] = ()): 
    if IS_POSTGRES:
        sql = sql.replace('?', '%s')
    return conn.execute(sql, params)


def now_dt() -> datetime:
    return datetime.now()


def now_iso() -> str:
    return now_dt().isoformat(timespec='seconds')


def parse_date(value: str) -> date:
    return datetime.strptime(value, '%Y-%m-%d').date()


def fmt_date(value: date) -> str:
    return value.isoformat()


def add_months_safe(d: date, months: int = 1) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, password_hash: str) -> bool:
    _, calc = hash_password(password, salt_hex)
    return hmac.compare_digest(calc, password_hash)


def init_db() -> None:
    with get_conn() as conn:
        if IS_POSTGRES:
            run(conn, '''
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            run(conn, '''
                CREATE TABLE IF NOT EXISTS sessions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            ''')
            run(conn, '''
                CREATE TABLE IF NOT EXISTS members (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    qq TEXT,
                    group_name TEXT,
                    join_date TEXT NOT NULL,
                    expire_date TEXT NOT NULL,
                    notes TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            run(conn, '''
                CREATE TABLE IF NOT EXISTS renewals (
                    id BIGSERIAL PRIMARY KEY,
                    member_id BIGINT NOT NULL,
                    renew_date TEXT NOT NULL,
                    months_added INTEGER NOT NULL DEFAULT 1,
                    before_expire_date TEXT NOT NULL,
                    after_expire_date TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    operator_user_id BIGINT
                )
            ''')
            run(conn, '''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    details TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
        else:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    qq TEXT,
                    group_name TEXT,
                    join_date TEXT NOT NULL,
                    expire_date TEXT NOT NULL,
                    notes TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS renewals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_id INTEGER NOT NULL,
                    renew_date TEXT NOT NULL,
                    months_added INTEGER NOT NULL DEFAULT 1,
                    before_expire_date TEXT NOT NULL,
                    after_expire_date TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    operator_user_id INTEGER
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    details TEXT,
                    created_at TEXT NOT NULL
                )
            ''')


def count_users() -> int:
    with get_conn() as conn:
        row = run(conn, 'SELECT COUNT(*) AS c FROM users WHERE active = 1').fetchone()
        return int(row['c'])


def create_user(username: str, display_name: str, password: str, role: str = 'admin') -> int:
    username = username.strip()
    display_name = display_name.strip() or username
    if not username or not password:
        raise ValueError('用户名和密码不能为空')
    salt_hex, password_hash = hash_password(password)
    now = now_iso()
    with get_conn() as conn:
        if IS_POSTGRES:
            cur = run(conn, '''INSERT INTO users
               (username, display_name, password_hash, password_salt, role, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)
               RETURNING id''', (username, display_name, password_hash, salt_hex, role, now, now))
            return int(cur.fetchone()['id'])
        cur = run(conn, '''INSERT INTO users
           (username, display_name, password_hash, password_salt, role, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)''', (username, display_name, password_hash, salt_hex, role, now, now))
        return int(cur.lastrowid)


def list_users() -> list[dict[str, Any]]:
    with get_conn() as conn:
        return run(conn, 'SELECT id, username, display_name, role, active, created_at, updated_at FROM users ORDER BY id ASC').fetchall()


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        return run(conn, 'SELECT id, username, display_name, role, active, created_at, updated_at FROM users WHERE id = ?', (user_id,)).fetchone()


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = run(conn, 'SELECT * FROM users WHERE username = ? AND active = 1', (username.strip(),)).fetchone()
        if not row:
            return None
        if not verify_password(password, row['password_salt'], row['password_hash']):
            return None
        return {'id': row['id'], 'username': row['username'], 'display_name': row['display_name'], 'role': row['role'], 'active': row['active']}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = now_dt()
    expires = now + timedelta(days=SESSION_DAYS)
    with get_conn() as conn:
        run(conn, 'INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)', (user_id, token, now.isoformat(timespec='seconds'), expires.isoformat(timespec='seconds')))
    return token


def get_user_by_session(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    now = now_iso()
    with get_conn() as conn:
        return run(conn, '''SELECT u.id, u.username, u.display_name, u.role, u.active, s.expires_at
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND u.active = 1 AND s.expires_at >= ?''', (token, now)).fetchone()


def delete_session(token: str) -> None:
    if not token:
        return
    with get_conn() as conn:
        run(conn, 'DELETE FROM sessions WHERE token = ?', (token,))


def add_audit_log(user_id: int | None, action: str, target_type: str, target_id: str = '', details: str = '') -> None:
    with get_conn() as conn:
        run(conn, 'INSERT INTO audit_logs (user_id, action, target_type, target_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?)', (user_id, action, target_type, target_id, details, now_iso()))


def list_audit_logs(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return run(conn, '''SELECT a.*, u.username, u.display_name FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT ?''', (limit,)).fetchall()


def add_member(name: str, qq: str, group_name: str, join_date: str, notes: str = '') -> int:
    jd = parse_date(join_date)
    expire_date = add_months_safe(jd, 1)
    now = now_iso()
    with get_conn() as conn:
        if IS_POSTGRES:
            cur = run(conn, '''INSERT INTO members
               (name, qq, group_name, join_date, expire_date, notes, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
               RETURNING id''', (name.strip(), qq.strip(), group_name.strip(), fmt_date(jd), fmt_date(expire_date), notes.strip(), now, now))
            return int(cur.fetchone()['id'])
        cur = run(conn, '''INSERT INTO members
           (name, qq, group_name, join_date, expire_date, notes, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)''', (name.strip(), qq.strip(), group_name.strip(), fmt_date(jd), fmt_date(expire_date), notes.strip(), now, now))
        return int(cur.lastrowid)


def list_members(active_only: bool = True, query: str = '') -> list[dict[str, Any]]:
    with get_conn() as conn:
        sql = 'SELECT * FROM members'
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append('active = 1')
        q = query.strip()
        if q:
            clauses.append('(name LIKE ? OR qq LIKE ? OR group_name LIKE ? OR notes LIKE ?)')
            like = f'%{q}%'
            params.extend([like, like, like, like])
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY expire_date ASC, id ASC'
        return run(conn, sql, tuple(params)).fetchall()


def get_member(member_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        return run(conn, 'SELECT * FROM members WHERE id = ?', (member_id,)).fetchone()


def renew_member(member_id: int, months: int = 1, note: str = '', operator_user_id: int | None = None) -> dict[str, Any]:
    with get_conn() as conn:
        member = run(conn, 'SELECT * FROM members WHERE id = ?', (member_id,)).fetchone()
        if not member:
            raise ValueError('member not found')
        today = date.today()
        current_expire = parse_date(member['expire_date'])
        base_date = current_expire if current_expire >= today else today
        new_expire = add_months_safe(base_date, months)
        now = now_iso()
        run(conn, 'UPDATE members SET expire_date = ?, updated_at = ? WHERE id = ?', (fmt_date(new_expire), now, member_id))
        run(conn, '''INSERT INTO renewals
           (member_id, renew_date, months_added, before_expire_date, after_expire_date, note, created_at, operator_user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (member_id, fmt_date(today), months, member['expire_date'], fmt_date(new_expire), note.strip(), now, operator_user_id))
        return run(conn, 'SELECT * FROM members WHERE id = ?', (member_id,)).fetchone()


def update_member(member_id: int, name: str, qq: str, group_name: str, join_date: str, expire_date: str, notes: str, active: bool = True) -> None:
    parse_date(join_date)
    parse_date(expire_date)
    with get_conn() as conn:
        run(conn, '''UPDATE members
           SET name = ?, qq = ?, group_name = ?, join_date = ?, expire_date = ?, notes = ?, active = ?, updated_at = ?
           WHERE id = ?''', (name.strip(), qq.strip(), group_name.strip(), join_date, expire_date, notes.strip(), 1 if active else 0, now_iso(), member_id))


def due_members(remind_days: int = 5, query: str = '') -> list[dict[str, Any]]:
    today = date.today()
    rows = list_members(active_only=True, query=query)
    out = []
    for row in rows:
        expire = parse_date(row['expire_date'])
        days_left = (expire - today).days
        if days_left <= remind_days:
            row = dict(row)
            row['days_left'] = days_left
            out.append(row)
    out.sort(key=lambda x: (x['days_left'], x['expire_date'], x['id']))
    return out


def dashboard_payload(remind_days: int = 5, query: str = '') -> dict[str, Any]:
    members = list_members(active_only=True, query=query)
    due = due_members(remind_days=remind_days, query=query)
    today = date.today()
    summary = {
        'today': fmt_date(today),
        'total_active': len(members),
        'due_count': len(due),
        'expired_count': sum(1 for m in due if m['days_left'] < 0),
        'today_due_count': sum(1 for m in due if m['days_left'] == 0),
        'upcoming_count': sum(1 for m in due if 0 < m['days_left'] <= remind_days),
        'remind_days': remind_days,
        'query': query,
        'db_backend': DB_BACKEND,
    }
    return {'summary': summary, 'due': due, 'members': members}


def list_renewals(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return run(conn, '''SELECT r.*, m.name, m.qq, u.username AS operator_username, u.display_name AS operator_display_name
           FROM renewals r JOIN members m ON m.id = r.member_id LEFT JOIN users u ON u.id = r.operator_user_id
           ORDER BY r.id DESC LIMIT ?''', (limit,)).fetchall()
