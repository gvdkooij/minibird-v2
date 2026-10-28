import json
import re
import sqlite3
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.domain import calculate
from app.db import backup, connect, migrate

SECRET='test-secret-'*8

@pytest.fixture
def ctx(tmp_path):
    db=str(tmp_path/'app.sqlite')
    client=TestClient(create_app(db,SECRET,False))
    return client,db

def token(c,path='/'):
    r=c.get(path)
    assert r.status_code==200,r.text
    m=re.search('name="csrf" value="([^"]+)"',r.text)
    assert m,r.text
    return m[1]

def post(c,path,data=None,page='/'):
    return c.post(path,data={'csrf':token(c,page),**(data or {})},follow_redirects=False)

def setup(c):
    r=post(c,'/setup',{'email':'admin@example.nl','password':'correct horse battery staple'},'/setup')
    assert r.status_code==303,r.text

def seed(c):
    setup(c)
    assert post(c,'/settings',{'name':'Studio Noord','address':'Gracht 1, Utrecht','iban':'NL00 TEST','smtp_host':'smtp.example.nl','smtp_from':'info@example.nl','smtp_user':'user','smtp_password':'not-plaintext'}).status_code==303
    assert post(c,'/customers',{'name':'Klant <script>alert(1)</script>','email':'klant@example.nl','address':'Straat 2','contact':'Jan','kvk':'123','vat':'NL123'}).status_code==303

def doc(c,kind='invoice',due=None):
    r=post(c,'/documents',{'kind':kind,'customer_id':'1','due':due or date.today().isoformat(),'description':'Advies','quantity':'2.5','price':'10.01','rate':'21'})
    assert r.status_code==303,r.text
    return r.headers['location']

def test_auth_csrf_setup_logout(ctx):
    c,db=ctx
    assert c.get('/customers',follow_redirects=False).status_code==303
    assert c.post('/setup',data={'email':'x'}).status_code==403
    assert post(c,'/setup',{'email':'bad','password':'short'},'/setup').status_code==422
    setup(c)
    assert post(c,'/setup',{'email':'x@example.nl','password':'long enough password'}).status_code==409
    assert c.post('/logout').status_code==403
    assert post(c,'/logout').status_code==303
    for _ in range(5):
        assert post(c,'/login',{'email':'admin@example.nl','password':'bad'},'/login').status_code==400
    assert post(c,'/login',{'email':'admin@example.nl','password':'correct horse battery staple'},'/login').status_code==429
    with connect(db) as conn: conn.execute('DELETE FROM attempts')
    assert post(c,'/login',{'email':'admin@example.nl','password':'correct horse battery staple'},'/login').status_code==303
    assert c.get('/').status_code==200
    with connect(db) as conn:
        assert conn.execute('SELECT password FROM admin').fetchone()[0].startswith('$argon2id$')

def test_customers_search_archive_delete_escape(ctx):
    c,db=ctx; seed(c)
    html=c.get('/customers').text
    assert '&lt;script&gt;' in html and '<script>alert' not in html
    assert 'Klant' in c.get('/customers?q=Klant').text
    assert 'Geen klanten' in c.get('/customers',params={'q':"' OR 1=1 --"}).text
    assert post(c,'/customers',{'id':'1','name':'Nieuw','email':'a@example.nl','address':'Adres'}).status_code==303
    assert post(c,'/customers/1/archive').status_code==303
    assert '<strong>Nieuw</strong>' not in c.get('/customers').text
    assert 'Nieuw' in c.get('/customers?archived=1').text
    post(c,'/customers/1/restore')
    assert post(c,'/customers/1/delete').status_code==303
    assert c.get('/customers/1').status_code==404

def test_quote_invoice_full_http_workflow(ctx):
    c,db=ctx; seed(c)
    q=doc(c,'quote')
    assert q=='/documents/1'
    assert post(c,q+'/paid').status_code==409
    assert post(c,q+'/issue').status_code==303
    assert post(c,q+'/accept').status_code==303
    r=post(c,q+'/convert'); invoice=r.headers['location']
    assert post(c,q+'/convert').headers['location']==invoice
    assert c.get('/documents?kind=quote&q=O').status_code==200
    assert post(c,'/customers/1/delete').status_code==409
    pdf=c.get(invoice+'/pdf')
    assert pdf.content.startswith(b'%PDF-') and len(pdf.content)>1000
    assert pdf.headers['content-disposition']=='attachment; filename="F'+str(date.today().year)+'-0001.pdf"'
    assert post(c,invoice+'/issue').status_code==303
    assert post(c,invoice+'/delete').status_code==409
    assert post(c,invoice+'/paid').status_code==303
    assert 'Betaald' in c.get(invoice).text
    assert post(c,invoice+'/paid').status_code==409
    with connect(db) as conn:
        row=conn.execute('SELECT * FROM documents WHERE kind="invoice"').fetchone()
        assert row['total']==3029
        assert json.loads(row['company'])['name']=='Studio Noord'

def test_overdue_and_immutable_snapshot(ctx):
    c,db=ctx; seed(c)
    d=doc(c,due=(date.today()-timedelta(days=1)).isoformat())
    post(c,d+'/issue')
    assert 'Verlopen' in c.get(d).text
    assert 'F'+str(date.today().year) in c.get('/documents?status=overdue').text
    post(c,'/settings',{'name':'Changed','address':'Elsewhere'})
    assert 'Studio Noord' in c.get(d).text

def test_draft_delete_sequence(ctx):
    c,db=ctx; seed(c)
    d=doc(c); post(c,d+'/delete'); d=doc(c)
    assert f'F{date.today().year}-0002' in c.get(d).text

def test_smtp_encrypted_mocked_send_and_failure(ctx):
    c,db=ctx; seed(c); d=doc(c)
    with connect(db) as conn:
        s=conn.execute('SELECT data FROM settings').fetchone()[0]
        assert 'not-plaintext' not in s
    assert 'not-plaintext' not in c.get('/settings').text
    server=MagicMock()
    with patch('app.main.smtplib.SMTP') as smtp:
        smtp.return_value.__enter__.return_value=server
        assert post(c,'/settings/test').status_code==200
        server.send_message.assert_not_called()
        assert post(c,d+'/email').status_code==303
        server.starttls.assert_called()
        server.login.assert_called_with('user','not-plaintext')
        msg=server.send_message.call_args[0][0]
        assert msg['To']=='klant@example.nl'
        assert next(msg.iter_attachments()).get_content_type()=='application/pdf'
    with patch('app.main.smtplib.SMTP',side_effect=OSError('secret error')):
        r=post(c,d+'/email'); assert r.status_code==502 and 'secret error' not in r.text

def test_persistence_migration_backup_restart(ctx,tmp_path):
    c,db=ctx; seed(c); doc(c)
    migrate(db); migrate(db)
    dest=tmp_path/'backup.sqlite'; backup(db,dest)
    with pytest.raises(ValueError): backup(db,dest)
    with sqlite3.connect(dest) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('PRAGMA user_version').fetchone()[0]==4
        assert conn.execute('SELECT count(*) FROM documents').fetchone()[0]==1
    restarted=TestClient(create_app(str(dest),SECRET,False))
    assert post(restarted,'/login',{'email':'admin@example.nl','password':'correct horse battery staple'},'/login').status_code==303
    assert 'Advies' in restarted.get('/documents/1').text

def test_security_headers_config_and_validation(ctx):
    c,db=ctx; seed(c)
    assert c.get('/').headers['x-frame-options']=='DENY'
    assert "default-src 'self'" in c.get('/').headers['content-security-policy']
    assert post(c,'/documents',{'kind':'invalid'}).status_code==422
    assert c.get('/documents/999').status_code==404
    assert c.get('/documents/new?kind=evil').status_code==422
    assert post(c,'/customers',{'name':'x','email':'bad\r\nBcc: a@example.nl','address':'a'}).status_code==422
    with pytest.raises(RuntimeError): create_app(db,'short')
    secure=TestClient(create_app(db,SECRET,True),base_url='https://testserver')
    assert 'secure' in secure.get('/login').headers['set-cookie'].lower()

@pytest.mark.parametrize('quantity,price,rate,net,vat',[('1','0.005','21',1,0),('2.5','10.01','21',2503,526),('3','9.99','9',2997,270),('1','10','0',1000,0)])
def test_money(quantity,price,rate,net,vat):
    line=calculate(['Werk'],[quantity],[price],[rate])[0]
    assert (line['net'],line['vat'])==(net,vat)

@pytest.mark.parametrize('q,p,r',[('NaN','1','21'),('-1','1','21'),('1','-1','21'),('1','1','19'),('Infinity','1','21')])
def test_invalid_money(q,p,r):
    with pytest.raises(ValueError): calculate(['Werk'],[q],[p],[r])


def test_csrf_requires_issued_token(ctx):
    c,db=ctx
    assert c.post('/setup',data={'csrf':'!','email':'bad@example.nl','password':'long password'}).status_code==403
    setup(c)
    assert c.post('/customers',data={'csrf':'!','name':'x','address':'y'}).status_code==403
    assert c.post('/customers',data={'csrf':'é'}).status_code==403


@pytest.mark.parametrize('path',['/settings','/customers','/documents','/documents/1','/documents/1/pdf'])
def test_private_routes_require_login(ctx,path):
    c,db=ctx
    assert c.get(path,follow_redirects=False).status_code==303


def test_future_schema_and_missing_backup_source(tmp_path):
    db=str(tmp_path/'future.sqlite')
    migrate(db)
    with connect(db) as conn: conn.execute('PRAGMA user_version=5')
    with pytest.raises(RuntimeError): migrate(db)
    with pytest.raises(ValueError): backup(tmp_path/'missing.sqlite',tmp_path/'bad.sqlite')


def test_customer_validation_and_document_guards(ctx):
    c,db=ctx; seed(c)
    assert post(c,'/customers',{'id':'bad','name':'x','address':'y'}).status_code==422
    assert post(c,'/customers',{'id':'999','name':'x','address':'y'}).status_code==404
    r=post(c,'/documents',{'kind':'invoice','customer_id':'1','due':'bad','description':'x','quantity':'1','price':'1','rate':'21'})
    assert r.status_code==422
    post(c,'/customers/1/archive')
    r=post(c,'/documents',{'kind':'invoice','customer_id':'1','due':date.today().isoformat(),'description':'x','quantity':'1','price':'1','rate':'21'})
    assert r.status_code==422
