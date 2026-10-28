import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from app.db import connect, migrate
from app.main import create_app
from test_app import SECRET, ctx, setup, post, token
from test_imports import VCF
from test_uploads import start, pieces


def test_delayed_anonymous_cookie_cannot_erase_login_during_upload(ctx):
    c,db=ctx
    c.get('/setup')
    anonymous=list(c.cookies.jar)
    setup(c)
    auth=c.cookies.get('minibird_session')
    id,headers=start(c)
    assert c.put(f'/imports/uploads/{id}/chunks/0',content=VCF,headers=headers).status_code==200
    # Deliver a response cookie captured before login after the file was sent.
    for old_cookie in anonymous: c.cookies.jar.set_cookie(old_cookie)
    response=c.post(f'/imports/uploads/{id}/complete',headers=headers)
    assert response.status_code==200,response.text
    assert c.get(response.json()['preview']).status_code==200
    assert c.cookies.get('minibird_session')==auth
    assert 'set-cookie' not in response.headers


def test_auth_state_is_server_side_and_survives_restart(ctx):
    c,db=ctx;setup(c)
    auth=c.cookies.get('minibird_session')
    assert len(auth)==43
    for _ in range(4):
        preview=pieces(c,VCF)
        assert c.get(preview).status_code==200
        assert c.cookies.get('minibird_session')==auth
    key=hmac.new(SECRET.encode(),auth.encode(),hashlib.sha256).hexdigest()
    with connect(db) as conn:
        row=conn.execute('SELECT data FROM web_sessions WHERE id=?',(key,)).fetchone()
        data=json.loads(row[0])
        assert data['admin'] is True and len(data['imports'])==3
        assert auth not in row[0] and key!=auth
    restarted=TestClient(create_app(db,SECRET,False))
    restarted.cookies.set('minibird_session',auth,domain='testserver.local',path='/')
    assert restarted.get('/imports').status_code==200
    assert 'session' not in {cookie.name for cookie in restarted.cookies.jar}


def test_logout_revokes_cookie_and_old_cookie_cannot_restore_auth(ctx):
    c,db=ctx;setup(c)
    auth=c.cookies.get('minibird_session')
    csrf=token(c,'/imports')
    assert post(c,'/logout').status_code==303
    c.cookies.set('minibird_session',auth,domain='testserver.local',path='/')
    r=c.post('/imports/uploads/start',json={'filename':'x.vcf','size':1},headers={'Accept':'application/json','X-CSRF-Token':csrf})
    assert r.status_code==401
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM web_sessions').fetchone()[0]==0


def test_expired_server_session_cannot_be_used(ctx):
    c,db=ctx;setup(c)
    csrf=token(c,'/imports')
    with connect(db) as conn: conn.execute('UPDATE web_sessions SET expires=?',(time.time()-1,))
    response=c.post('/imports/uploads/start',json={'filename':'x.vcf','size':1},headers={'Accept':'application/json','X-CSRF-Token':csrf})
    assert response.status_code==401
    assert response.json()['code']=='MB-COOKIE-INVALID'


def test_schema_three_upgrade_preserves_archive_and_customer(ctx):
    c,db=ctx;setup(c)
    post(c,'/customers',{'name':'Bestaand','address':'Adres'})
    with connect(db) as conn:
        conn.execute('DROP TABLE web_sessions')
        conn.execute('PRAGMA user_version=3')
    migrate(db);migrate(db)
    with connect(db) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==4
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM web_sessions').fetchone()[0]==0


def test_parallel_requests_merge_state_without_overwriting_login(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import anyio
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from app.sessions import ServerSessionMiddleware
    path=tmp_path/'parallel.sqlite';migrate(path)
    gate=threading.Barrier(2)
    async def login(request):
        request.session.clear();request.session['admin']=True
        return JSONResponse({'ok':True})
    async def add(request):
        before=list(request.session.get('uploads',[]))
        await anyio.to_thread.run_sync(gate.wait)
        request.session['uploads']=before+[request.path_params['id']]
        return JSONResponse({'ok':True})
    # Minimal middleware harness, not application authentication routes.
    app=Starlette(routes=[Route('/login',login),Route('/add/{id}',add)])
    app.add_middleware(ServerSessionMiddleware,database=path,secret_key=SECRET,secure=False)
    client=TestClient(app);client.get('/login')
    auth=client.cookies.get('minibird_session')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda id:client.get('/add/'+id),['first','second']))
    assert all(r.status_code==200 and 'set-cookie' not in r.headers for r in results)
    assert client.cookies.get('minibird_session')==auth
    with connect(path) as db:
        data=json.loads(db.execute('SELECT data FROM web_sessions').fetchone()[0])
        assert data['admin'] and set(data['uploads'])=={'first','second'}


def test_late_authenticated_response_cannot_undo_logout(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import anyio
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from app.sessions import ServerSessionMiddleware
    path=tmp_path/'late.sqlite';migrate(path)
    started=threading.Event();release=threading.Event()
    async def login(request):
        request.session.clear();request.session['admin']=True
        return JSONResponse({'ok':True})
    async def late(request):
        request.session['uploads']=['late']
        started.set()
        await anyio.to_thread.run_sync(release.wait)
        return JSONResponse({'ok':True})
    async def logout(request):
        request.session.clear()
        return JSONResponse({'ok':True})
    app=Starlette(routes=[Route('/login',login),Route('/late',late),Route('/logout',logout)])
    app.add_middleware(ServerSessionMiddleware,database=path,secret_key=SECRET,secure=False)
    client=TestClient(app);client.get('/login')
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(client.get,'/late')
        assert started.wait(timeout=5)
        try: assert client.get('/logout').status_code==200
        finally: release.set()
        assert 'set-cookie' not in task.result(timeout=5).headers
    assert not client.cookies.get('minibird_session')
    with connect(path) as db: assert db.execute('SELECT count(*) FROM web_sessions').fetchone()[0]==0


def test_secret_rotation_invalidates_existing_login(ctx):
    c,db=ctx;setup(c)
    auth=c.cookies.get('minibird_session')
    changed=TestClient(create_app(db,SECRET+'rotated',False))
    changed.cookies.set('minibird_session',auth,domain='testserver.local',path='/')
    response=changed.get('/imports',headers={'Accept':'application/json'})
    assert response.status_code==401 and response.json()['code']=='MB-COOKIE-INVALID'
