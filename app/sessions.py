"""Server-side authenticated sessions; anonymous responses cannot replace login.

Only login/logout change the authenticated cookie. A delayed pre-login response
may update the separate pre-login CSRF cookie, never the authenticated session.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from http.cookies import SimpleCookie

from itsdangerous import BadSignature, TimestampSigner
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from .db import connect

AUTH_COOKIE = 'minibird_session'
ANON_COOKIE = 'minibird_prelogin'
MAX_AGE = 28800


class Session(dict):
    cleared = False

    def clear(self):
        self.cleared = True
        super().clear()


def cookie_header(name, value, secure, expired=False):
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]['path'] = '/'
    cookie[name]['httponly'] = True
    cookie[name]['samesite'] = 'Lax'
    cookie[name]['max-age'] = 0 if expired else MAX_AGE
    if secure: cookie[name]['secure'] = True
    if expired: cookie[name]['expires'] = 'Thu, 01 Jan 1970 00:00:00 GMT'
    return cookie.output(header='').strip()


class ServerSessionMiddleware:
    def __init__(self, app, database, secret_key, secure):
        self.app = app
        self.database = database
        self.secret_key = secret_key.encode()
        self.signer = TimestampSigner(secret_key, salt='minibird-prelogin')
        self.secure = secure

    def auth_hash(self, token):
        return hmac.new(self.secret_key,token.encode(),hashlib.sha256).hexdigest()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        connection = HTTPConnection(scope)
        auth_cookie = connection.cookies.get(AUTH_COOKIE, '')
        auth_key = self.auth_hash(auth_cookie) if auth_cookie else None
        auth = None
        if auth_key:
            with connect(self.database) as db:
                auth = db.execute('SELECT data,expires FROM web_sessions WHERE id=? AND expires>?',
                                  (auth_key, time.time())).fetchone()
        initial = json.loads(auth['data']) if auth else {}
        if not auth:
            raw = connection.cookies.get(ANON_COOKIE, '')
            if raw:
                try:
                    decoded = self.signer.unsign(raw, max_age=MAX_AGE)
                    data = json.loads(base64.b64decode(decoded))
                    # Anonymous cookies can contain only a CSRF token, never auth.
                    if isinstance(data, dict) and isinstance(data.get('csrf'), str):
                        initial = {'csrf': data['csrf']}
                except (BadSignature, ValueError, UnicodeError):
                    pass
        session = Session(initial)
        scope['session'] = session
        scope['minibird_auth_state'] = 'authenticated' if auth else 'invalid' if auth_cookie else 'missing'

        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers.add_vary_header('Cookie')
                if session.get('admin') and (not auth or session.cleared):
                    # Issue/rotate once at a verified login, not on upload requests.
                    session.setdefault('csrf', secrets.token_urlsafe(32))
                    token = secrets.token_urlsafe(32)
                    key = self.auth_hash(token)
                    with connect(self.database) as db:
                        db.execute('DELETE FROM web_sessions WHERE expires<=?', (time.time(),))
                        if auth_key: db.execute('DELETE FROM web_sessions WHERE id=?', (auth_key,))
                        db.execute('INSERT INTO web_sessions VALUES(?,?,?)',
                                   (key, time.time()+MAX_AGE, json.dumps(session)))
                    headers.append('Set-Cookie', cookie_header(AUTH_COOKIE,token,self.secure))
                    headers.append('Set-Cookie', cookie_header(ANON_COOKIE,'',self.secure,True))
                elif auth and session.cleared and not session.get('admin'):
                    with connect(self.database) as db:
                        db.execute('DELETE FROM web_sessions WHERE id=?', (auth_key,))
                    headers.append('Set-Cookie', cookie_header(AUTH_COOKIE,'',self.secure,True))
                    headers.append('Set-Cookie', cookie_header(ANON_COOKIE,'',self.secure,True))
                elif auth:
                    # Merge only changed fields into the latest row. Concurrent
                    # requests must not replay a whole old snapshot over a new one.
                    changed = {k:v for k,v in session.items() if k not in initial or v!=initial[k]}
                    removed = set(initial)-set(session)
                    if changed or removed:
                        with connect(self.database) as db:
                            db.execute('BEGIN IMMEDIATE')
                            current = db.execute('SELECT data FROM web_sessions WHERE id=? AND expires>?',
                                                 (auth_key,time.time())).fetchone()
                            # Never resurrect a session logged out in another tab.
                            if current:
                                merged = json.loads(current['data'])
                                for key in removed: merged.pop(key,None)
                                for key,value in changed.items():
                                    if key in ('imports','uploads'):
                                        added = [item for item in value if item not in initial.get(key,[])]
                                        merged[key] = list(dict.fromkeys(merged.get(key,[])+added))[-3:]
                                    elif key == 'csrf':
                                        merged.setdefault(key,value)
                                    else:
                                        merged[key] = value
                                db.execute('UPDATE web_sessions SET data=? WHERE id=?',
                                           (json.dumps(merged),auth_key))
                    # No Set-Cookie: late upload/static responses cannot roll back login.
                elif session.get('csrf') and session != initial:
                    data = base64.b64encode(json.dumps({'csrf':session['csrf']}).encode())
                    value = self.signer.sign(data).decode()
                    headers.append('Set-Cookie',cookie_header(ANON_COOKIE,value,self.secure))
            await send(message)

        await self.app(scope, receive, send_wrapper)
