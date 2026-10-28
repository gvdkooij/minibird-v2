import json
import time
from fastapi.testclient import TestClient
import pytest

from app.db import connect, migrate
from app.importing import CHUNK_SIZE, MAX_UPLOAD, ImportProblem, parse_upload
from app.main import create_app
from test_app import SECRET, ctx, setup, token, post
from test_imports import VCF, export_files, workbook, zipped, upload, confirm


def start(c,data=VCF,name='contacts.vcf'):
    headers={'X-CSRF-Token':token(c,'/imports')}
    response=c.post('/imports/uploads/start',json={'filename':name,'size':len(data)},headers=headers)
    assert response.status_code==200,response.text
    return response.json()['id'],headers


def pieces(c,data,name='contacts.vcf'):
    id,headers=start(c,data,name)
    for index,offset in enumerate(range(0,len(data),CHUNK_SIZE)):
        r=c.put(f'/imports/uploads/{id}/chunks/{index}',content=data[offset:offset+CHUNK_SIZE],headers=headers)
        assert r.status_code==200,r.text
    r=c.post(f'/imports/uploads/{id}/complete',headers=headers)
    assert r.status_code==200,r.text
    return r.json()['preview']


def test_chunk_upload_order_retries_and_confirmation(ctx):
    c,db=ctx;setup(c)
    data=VCF.replace(b'END:VCARD',b'NOTE:'+b'x'*(CHUNK_SIZE+20)+b'\nEND:VCARD')
    id,headers=start(c,data)
    base=f'/imports/uploads/{id}'
    assert c.post(base+'/complete',headers=headers).status_code==409
    assert c.put(base+'/chunks/1',content=b'out of order',headers=headers).status_code==409
    assert c.put(base+'/chunks/0',content=b'x'*(CHUNK_SIZE+1),headers=headers).status_code==413
    first=c.put(base+'/chunks/0',content=data[:CHUNK_SIZE],headers=headers)
    assert first.status_code==200
    assert c.put(base+'/chunks/0',content=data[:CHUNK_SIZE],headers=headers).json()==first.json()
    assert c.put(base+'/chunks/0',content=b'y'*CHUNK_SIZE,headers=headers).status_code==409
    assert c.put(base+'/chunks/1',content=b'short',headers=headers).status_code==422
    assert c.put(base+'/chunks/1',content=data[CHUNK_SIZE:],headers=headers).status_code==200
    r=c.post(base+'/complete',headers=headers);assert r.status_code==200,r.text
    preview=r.json()['preview']
    assert c.post(base+'/complete',headers=headers).json()==r.json()
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM import_chunks').fetchone()[0]==0
    assert confirm(c,preview).status_code==303
    assert c.get(preview+'/source').content==data
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1


def test_chunk_auth_limits_session_isolation_and_cancel(ctx):
    c,db=ctx
    assert c.post('/imports/uploads/start',json={'filename':'a.vcf','size':1},follow_redirects=False).status_code==303
    setup(c)
    assert c.post('/imports/uploads/start',json={'filename':'a.vcf','size':1}).status_code==403
    headers={'X-CSRF-Token':token(c,'/imports')}
    for metadata in ({'filename':'a.vcf','size':MAX_UPLOAD+1},{'filename':'a.vcf','size':0},{'filename':'a.exe','size':5}):
        assert c.post('/imports/uploads/start',json=metadata,headers=headers).status_code in (413,422)
    assert c.post('/imports/uploads/start',content=b'x'*4097,headers=headers).status_code==413
    id,headers=start(c)
    base=f'/imports/uploads/{id}'
    other=TestClient(create_app(db,SECRET,False))
    post(other,'/login',{'email':'admin@example.nl','password':'correct horse battery staple'},'/login')
    other_headers={'X-CSRF-Token':token(other,'/imports')}
    assert other.put(base+'/chunks/0',content=VCF,headers=other_headers).status_code==404
    assert c.put(base+'/chunks/0',content=VCF).status_code==403
    assert c.put(base+'/chunks/0',content=VCF,headers=headers).status_code==200
    assert c.delete(base,headers=headers).status_code==200
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM import_chunks').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM import_uploads').fetchone()[0]==0


def test_finished_upload_preview_cancel_and_pruning(ctx):
    c,db=ctx;setup(c)
    previews=[pieces(c,VCF) for _ in range(4)]
    assert c.get(previews[0]).status_code==404
    assert post(c,previews[-1]+'/cancel',page=previews[-1]).status_code==303
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM import_batches').fetchone()[0]==2
        assert conn.execute('SELECT count(*) FROM import_uploads').fetchone()[0]==2
    id,headers=start(c)
    with connect(db) as conn: conn.execute('UPDATE import_uploads SET created=? WHERE id=?',(time.time()-4000,id))
    assert c.post(f'/imports/uploads/{id}/complete',headers=headers).status_code==404
    start(c)
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM import_uploads WHERE id=?',(id,)).fetchone()[0]==0


def test_exempt_ubl_missing_percent_and_undated_quote(ctx):
    files=export_files()
    xml='sales_invoices_ubl_archive/2024-0001.xml'
    data=files[xml].replace('<cbc:Percent>21</cbc:Percent>','<cbc:ID>O</cbc:ID>').replace('<cbc:TaxAmount>208.26</cbc:TaxAmount>','<cbc:TaxAmount>0</cbc:TaxAmount>').replace('<cbc:TaxInclusiveAmount>1200</cbc:TaxInclusiveAmount>','<cbc:TaxInclusiveAmount>991.74</cbc:TaxInclusiveAmount>')
    files[xml]=data
    files['sales_invoices/invoices.xlsx']=workbook({'Facturen':[['id','factuurnummer','status','klantnummer','valuta','totaalprijs inclusief btw'],['i1','2024-0001','paid','1','EUR',991.74]]})
    files['estimates/quotes.xlsx']=workbook({'Offertes':[['id','offertenummer','status','offerte datum','vervaldatum','klantnummer','valuta','totaalprijs exclusief btw','totaalprijs inclusief btw'],['q1','Concept #3','draft',None,'2026-11-11','1','EUR',100,100]]})
    files['estimates_details/quote-lines.xlsx']=workbook({'Regels':[['offertenummer','btw','totaalprijs exclusief btw inclusief korting','aantal (decimaal)','prijs','omschrijving'],['Concept #3','Btw vrijgesteld',100,1,100,'Conceptwerk']]})
    files['estimates_archive/2026/draft_3.pdf']=files.pop('estimates_archive/2024/O2024-0020.pdf')
    raw=zipped(files); result=parse_upload('archive.zip',raw)
    assert result['documents'][0]['lines'][0]['vat']==0
    assert result['documents'][0]['lines'][0]['tax_label']=='Geen btw'
    quote=result['documents'][1]
    assert quote['number']=='Concept #3' and quote['date']==''
    assert quote['lines'][0]['tax_label']=='Btw vrijgesteld'
    c,db=ctx;setup(c)
    preview=pieces(c,raw,'archive.zip');confirm(c,preview)
    with connect(db) as conn: id=conn.execute("SELECT id FROM documents WHERE kind='quote'").fetchone()[0]
    assert 'Nog niet gedateerd' in c.get(f'/documents/{id}').text
    assert 'Btw vrijgesteld' in c.get(f'/documents/{id}').text
    response=c.get(f'/documents/{id}/pdf')
    assert response.content==files['estimates_archive/2026/draft_3.pdf']
    assert response.headers['content-disposition']=='attachment; filename="Concept__3.pdf"'
    files[xml]=data.replace('<cbc:ID>O</cbc:ID>','<cbc:ID>S</cbc:ID>')
    with pytest.raises(ImportProblem):parse_upload('archive.zip',zipped(files))


def test_session_cookie_allows_safe_top_level_return_and_keeps_csrf(ctx):
    c,db=ctx;setup(c)
    response=c.get('/imports')
    assert 'samesite=lax' in response.headers['set-cookie'].lower()
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert c.post('/imports/uploads/start',json={'filename':'a.vcf','size':1},headers={'Origin':'https://other.example'}).status_code==403


def test_schema_two_to_three_preserves_data(tmp_path):
    import sqlite3
    path=tmp_path/'database.sqlite';migrate(path)
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE import_chunks');db.execute('DROP TABLE import_uploads')
        db.execute("INSERT INTO customers(name,email,address,kvk,vat,contact) VALUES('Oud','','Adres','','','')")
        db.execute('PRAGMA user_version=2')
    migrate(path);migrate(path)
    with connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert db.execute('SELECT name FROM customers').fetchone()[0]=='Oud'
        assert db.execute('SELECT count(*) FROM import_uploads').fetchone()[0]==0


def test_current_csrf_only_for_authenticated_session(ctx):
    c,db=ctx
    assert c.get('/imports/token',follow_redirects=False).status_code==303
    setup(c)
    old=token(c,'/imports')
    response=c.get('/imports/token')
    assert response.json()['csrf']==old
    assert response.headers['cache-control']=='no-store'
    assert 'access-control-allow-origin' not in response.headers
    assert c.post('/imports/uploads/start',headers={'X-CSRF-Token':'stale'},json={'filename':'x.vcf','size':1}).status_code==403


def test_legacy_import_still_recognized_after_tax_label_upgrade(ctx):
    from app.importing import legacy_document_fingerprint
    c,db=ctx;setup(c)
    raw=zipped(export_files());payload=parse_upload('archive.zip',raw)
    preview=pieces(c,raw,'archive.zip');confirm(c,preview)
    with connect(db) as conn:
        for doc in payload['documents']:
            id=conn.execute('SELECT id FROM documents WHERE number=?',(doc['number'],)).fetchone()[0]
            conn.execute('UPDATE document_imports SET fingerprint=? WHERE document_id=?',(legacy_document_fingerprint(doc),id))
    preview=pieces(c,raw,'archive.zip')
    html=c.get(preview).text
    assert 'Al aanwezig' in html and 'Het nummer bestaat met andere gegevens' not in html
