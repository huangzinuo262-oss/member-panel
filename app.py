from http import cookies
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import os
import secrets

from config import APP_HOST, APP_PORT, APP_SECURE_COOKIES
from db import (
    add_audit_log,
    add_member,
    authenticate_user,
    count_users,
    create_session,
    create_user,
    dashboard_payload,
    delete_session,
    get_member,
    get_user_by_session,
    init_db,
    list_audit_logs,
    list_renewals,
    list_users,
    renew_member,
    update_member,
)

BASE_DIR = Path(__file__).resolve().parent
HTML_PATH = BASE_DIR / 'templates' / 'index.html'
DEFAULT_USERS_ENV = os.environ.get('MEMBER_PANEL_USERS', '').strip()


def ensure_default_users():
    if count_users() > 0:
        return
    if not DEFAULT_USERS_ENV:
        raise RuntimeError('MEMBER_PANEL_USERS 未配置，拒绝使用弱默认账号初始化')
    for item in DEFAULT_USERS_ENV.split(','):
        item = item.strip()
        if not item:
            continue
        parts = item.split(':')
        if len(parts) < 3:
            continue
        username, password, display_name = parts[0].strip(), parts[1].strip(), parts[2].strip()
        role = parts[3].strip() if len(parts) >= 4 and parts[3].strip() else ('partner' if username.lower() == 'partner' else 'admin')
        if username and password:
            create_user(username, display_name, password, role=role)


class AppHandler(BaseHTTPRequestHandler):
    def _cookie_flags(self) -> str:
        flags = 'Path=/; HttpOnly; SameSite=Lax'
        if APP_SECURE_COOKIES:
            flags += '; Secure'
        return flags

    def _csrf_token(self) -> str:
        c = self._cookies()
        morsel = c.get('member_csrf')
        return morsel.value if morsel else ''

    def _ensure_csrf_cookie(self) -> tuple[str, str] | None:
        token = self._csrf_token()
        if token:
            return None
        token = secrets.token_urlsafe(24)
        return ('Set-Cookie', f'member_csrf={token}; {self._cookie_flags()}; Max-Age=2592000')

    def _response_csrf_token(self, extra_headers: list[tuple[str, str]] | None = None) -> str:
        token = self._csrf_token()
        if token:
            return token
        if extra_headers:
            for key, value in extra_headers:
                if key.lower() == 'set-cookie' and value.startswith('member_csrf='):
                    return value.split(';', 1)[0].split('=', 1)[1]
        return ''

    def _page_html(self, extra_headers: list[tuple[str, str]] | None = None) -> str:
        html = HTML_PATH.read_text(encoding='utf-8')
        token = self._response_csrf_token(extra_headers)
        return html.replace('name="csrf_token" value=""', f'name="csrf_token" value="{token}"')

    def _check_csrf(self, data: dict[str, list[str]]) -> bool:
        form_token = (data.get('csrf_token') or [''])[0].strip()
        cookie_token = self._csrf_token()
        return bool(form_token and cookie_token and secrets.compare_digest(form_token, cookie_token))

    def _send(self, body: str, status: int = 200, content_type: str = 'text/html; charset=utf-8', extra_headers: list[tuple[str, str]] | None = None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))

    def _redirect(self, location: str = '/', extra_headers: list[tuple[str, str]] | None = None):
        self.send_response(302)
        self.send_header('Location', location)
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()

    def _cookies(self) -> cookies.SimpleCookie:
        c = cookies.SimpleCookie()
        raw = self.headers.get('Cookie') or ''
        c.load(raw)
        return c

    def _session_token(self) -> str:
        c = self._cookies()
        morsel = c.get('member_session')
        return morsel.value if morsel else ''

    def _current_user(self):
        token = self._session_token()
        return get_user_by_session(token)

    def _json(self, obj: dict, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False), status=status, content_type='application/json; charset=utf-8')

    def _require_role(self, user: dict, *roles: str) -> bool:
        if user.get('role') in roles:
            return True
        self._send('权限不足', status=403, content_type='text/plain; charset=utf-8')
        return False

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/login':
            headers: list[tuple[str, str]] = []
            csrf_cookie = self._ensure_csrf_cookie()
            if csrf_cookie:
                headers.append(csrf_cookie)
            self._send(self._page_html(headers), extra_headers=headers)
            return

        if parsed.path == '/logout':
            token = self._session_token()
            delete_session(token)
            self._redirect('/login', extra_headers=[
                ('Set-Cookie', f'member_session=; {self._cookie_flags()}; Max-Age=0'),
                ('Set-Cookie', f'member_csrf=; {self._cookie_flags()}; Max-Age=0'),
            ])
            return

        if parsed.path.startswith('/api/'):
            user = self._current_user()
            if not user:
                self._json({'ok': False, 'error': 'unauthorized'}, status=401)
                return

            if parsed.path == '/api/me':
                self._json({'ok': True, 'user': user})
                return

            if parsed.path == '/api/dashboard':
                qs = parse_qs(parsed.query)
                query = (qs.get('q') or [''])[0].strip()
                payload = dashboard_payload(remind_days=5, query=query)
                payload['renewals'] = list_renewals(limit=50)
                payload['audit_logs'] = list_audit_logs(limit=50)
                payload['users'] = list_users() if user.get('role') == 'admin' else []
                payload['current_user'] = user
                self._json(payload)
                return

            if parsed.path == '/api/member':
                qs = parse_qs(parsed.query)
                member_id = int((qs.get('id') or ['0'])[0] or '0')
                member = get_member(member_id)
                if not member:
                    self._json({'ok': False, 'error': 'not found'}, status=404)
                    return
                self._json({'ok': True, 'member': member})
                return

            self._json({'ok': False, 'error': 'not found'}, status=404)
            return

        if parsed.path == '/':
            user = self._current_user()
            if not user:
                self._redirect('/login')
                return
            headers: list[tuple[str, str]] = []
            csrf_cookie = self._ensure_csrf_cookie()
            if csrf_cookie:
                headers.append(csrf_cookie)
            self._send(self._page_html(headers), extra_headers=headers)
            return

        self._send('Not Found', status=404, content_type='text/plain; charset=utf-8')

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length).decode('utf-8')
        data = parse_qs(raw)

        if parsed.path == '/login':
            if not self._check_csrf(data):
                self._send('CSRF 校验失败，请刷新页面后重试', status=403, content_type='text/plain; charset=utf-8')
                return
            username = (data.get('username') or [''])[0].strip()
            password = (data.get('password') or [''])[0]
            user = authenticate_user(username, password)
            if not user:
                self._send('登录失败：用户名或密码错误', status=401, content_type='text/plain; charset=utf-8')
                return
            token = create_session(user['id'])
            add_audit_log(user['id'], 'login', 'session', token[:12], '用户登录')
            csrf_token = self._csrf_token() or secrets.token_urlsafe(24)
            self._redirect('/', extra_headers=[
                ('Set-Cookie', f'member_session={token}; {self._cookie_flags()}; Max-Age=2592000'),
                ('Set-Cookie', f'member_csrf={csrf_token}; {self._cookie_flags()}; Max-Age=2592000'),
            ])
            return

        user = self._current_user()
        if not user:
            self._redirect('/login')
            return
        if not self._check_csrf(data):
            self._send('CSRF 校验失败，请刷新页面后重试', status=403, content_type='text/plain; charset=utf-8')
            return

        try:
            if parsed.path == '/members/add':
                if not self._require_role(user, 'admin'):
                    return
                name = (data.get('name') or [''])[0].strip()
                qq = (data.get('qq') or [''])[0].strip()
                group_name = (data.get('group_name') or [''])[0].strip()
                join_date = (data.get('join_date') or [''])[0].strip()
                notes = (data.get('notes') or [''])[0].strip()
                if not name or not join_date:
                    self._send('姓名和入群时间不能为空', status=400, content_type='text/plain; charset=utf-8')
                    return
                member_id = add_member(name, qq, group_name, join_date, notes)
                add_audit_log(user['id'], 'add_member', 'member', str(member_id), f'name={name}, qq={qq}, group={group_name}')
                self._redirect('/')
                return

            if parsed.path == '/members/renew':
                member_id = int((data.get('member_id') or ['0'])[0] or '0')
                months = int((data.get('months') or ['1'])[0] or '1')
                note = (data.get('note') or [''])[0].strip()
                member = renew_member(member_id, months=months, note=note, operator_user_id=user['id'])
                add_audit_log(user['id'], 'renew_member', 'member', str(member_id), f'months={months}, expire={member["expire_date"]}')
                self._redirect('/')
                return

            if parsed.path == '/members/update':
                if not self._require_role(user, 'admin'):
                    return
                member_id = int((data.get('member_id') or ['0'])[0] or '0')
                name = (data.get('name') or [''])[0].strip()
                qq = (data.get('qq') or [''])[0].strip()
                group_name = (data.get('group_name') or [''])[0].strip()
                join_date = (data.get('join_date') or [''])[0].strip()
                expire_date = (data.get('expire_date') or [''])[0].strip()
                notes = (data.get('notes') or [''])[0].strip()
                active = ((data.get('active') or ['1'])[0].strip() != '0')
                if not member_id:
                    self._send('member_id 不能为空', status=400, content_type='text/plain; charset=utf-8')
                    return
                update_member(member_id, name, qq, group_name, join_date, expire_date, notes, active=active)
                add_audit_log(user['id'], 'update_member', 'member', str(member_id), f'name={name}, qq={qq}, group={group_name}, active={1 if active else 0}')
                self._redirect('/')
                return

        except Exception as exc:
            self._send(f'操作失败: {exc}', status=400, content_type='text/plain; charset=utf-8')
            return

        self._send('Not Found', status=404, content_type='text/plain; charset=utf-8')


def main():
    init_db()
    ensure_default_users()
    server = HTTPServer((APP_HOST, APP_PORT), AppHandler)
    print(f'Listening on http://{APP_HOST}:{APP_PORT}')
    server.serve_forever()


if __name__ == '__main__':
    main()
