"""Authenticated two-phase import. Uploaded files never enter the checkout."""
import base64
from collections import Counter
import hashlib
import json
import re
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import Response
from .db import connect
from .importing import MAX_UPLOAD, ImportProblem, fingerprint, norm, parse_upload


def plan_import(db, payload):
    existing = [dict(row) for row in db.execute('SELECT * FROM customers ORDER BY id')]
    links = {row['external_id']: row['customer_id'] for row in db.execute("SELECT * FROM import_links WHERE source='moneybird'")}
    plans = []
    for index, contact in enumerate(payload['contacts']):
        linked = links.get(contact['external_id']) if contact['external_id'] else None
        matches = [row for row in existing if norm(row['name'])==norm(contact['name'])]
        if linked:
            target = linked
            status = 'existing'
            reason = 'Eerder gekoppeld Moneybird-contact; bestaande gegevens blijven behouden.'
        elif len(matches)==1 and norm(matches[0]['name'])==norm(contact['name']) and (not matches[0]['email'] or not contact['email'] or norm(matches[0]['email'])==norm(contact['email'])):
            target = matches[0]['id']
            status = 'existing'
            reason = 'Bestaande of dubbele klant met dezelfde naam; bestaande gegevens blijven behouden.'
        elif matches:
            target = None
            status = 'conflict'
            reason = 'Meerdere mogelijke klanten of gedeeld e-mailadres. Handmatig beoordelen; wordt overgeslagen.'
        else:
            target = -(index+1)
            status = 'new'
            reason = 'Nieuwe klant.'
            if contact['email'] and any(norm(row['email'])==norm(contact['email']) for row in existing):
                reason += ' Dit e-mailadres komt ook bij een andere naam voor; de klanten blijven afzonderlijk.'
            existing.append({**contact,'id':target})
        plans.append({'index':index,'target':target,'status':status,'reason':reason})
    by_number = {c.get('customer_number'): p for c,p in zip(payload['contacts'],plans) if c.get('customer_number')}
    documents = []
    seen = set()
    for index, doc in enumerate(payload['documents']):
        customer_plan = by_number.get(doc.get('contact_key'))
        current = db.execute('SELECT d.id,i.fingerprint FROM documents d LEFT JOIN document_imports i ON i.document_id=d.id WHERE d.number=?',(doc['number'],)).fetchone()
        if doc['number'] in seen:
            status,reason='conflict','Documentnummer komt dubbel voor in dit bestand.'
        elif not customer_plan or customer_plan['status']=='conflict':
            status,reason='conflict','Klantkoppeling is niet eenduidig; document wordt overgeslagen.'
        elif current:
            status = 'existing' if current['fingerprint']==fingerprint(doc) else 'conflict'
            reason = 'Dit document is al geïmporteerd.' if status=='existing' else 'Het nummer bestaat met andere gegevens. Wordt niet overschreven.'
        else:
            status,reason='new','Nieuw historisch document, alleen-lezen.'
        documents.append({'index':index,'status':status,'reason':reason})
        seen.add(doc['number'])
    return {'contacts':plans,'documents':documents}


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()


def register_import_routes(app, database, render, require, form, go):
    def batch_for(db, request, id):
        batch = db.execute('SELECT * FROM import_batches WHERE id=?',(id,)).fetchone()
        if not batch: raise HTTPException(404,'Import verlopen. Upload het bestand opnieuw.')
        if not batch['confirmed'] and id not in request.session.get('imports',[]):
            raise HTTPException(404,'Import niet gevonden in deze sessie. Upload het bestand opnieuw.')
        return batch

    @app.get('/imports')
    def import_page(request:Request):
        require(request)
        with connect(database) as db:
            history=db.execute('SELECT id,filename,summary FROM import_batches WHERE confirmed=1 ORDER BY created DESC').fetchall()
        return render(request,'imports.html',history=history)

    @app.post('/imports/preview')
    async def preview(request:Request):
        # Authorization happens before multipart parsing. The stream limit applies
        # even to chunked requests, before Starlette can spool an oversized file.
        require(request)
        size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>MAX_UPLOAD+65536: raise HTTPException(413,'Upload maximaal 10 MB.')
            # The request body is bounded; cache it for the existing CSRF/form code.
            if size==len(chunk): body=bytearray()
            body.extend(chunk)
        request._body=bytes(body) if size else b''
        f=await form(request)
        upload=f.get('file')
        if not hasattr(upload,'read'): raise HTTPException(422,'Kies een bestand.')
        data=await upload.read(MAX_UPLOAD+1)
        await upload.close()
        filename=str(upload.filename or '').replace('\\','/').rsplit('/',1)[-1][:200]
        try: payload=parse_upload(filename,data)
        except ImportProblem as exc: raise HTTPException(422,str(exc)) from None
        with connect(database) as db:
            db.execute('DELETE FROM import_batches WHERE confirmed=0 AND created<?',(time.time()-3600,))
            # Keep at most three previews per session; remove cancelled/older raw uploads.
            old=list(request.session.get('imports',[]))
            for id in old[:-2]: db.execute('DELETE FROM import_batches WHERE id=? AND confirmed=0',(id,))
            id=secrets.token_urlsafe(24)
            plan=plan_import(db,payload)
            db.execute('INSERT INTO import_batches(id,created,filename,payload,original,summary) VALUES(?,?,?,?,?,?)',
                       (id,time.time(),filename,json.dumps(payload),data,json.dumps({'plan_hash':plan_hash(plan)})))
        request.session['imports']=(old+[id])[-3:]
        return go('/imports/'+id)

    @app.get('/imports/{id}')
    def preview_page(request:Request,id:str):
        require(request)
        with connect(database) as db:
            batch=batch_for(db,request,id)
            payload=json.loads(batch['payload'])
            plan=plan_import(db,payload) if not batch['confirmed'] else None
        if batch['confirmed']:
            return render(request,'import_done.html',batch=batch,summary=json.loads(batch['summary']))
        return render(request,'import_preview.html',batch=batch,payload=payload,plan=plan,
                      counts={key:Counter(p['status'] for p in plan[key]) for key in ('contacts','documents')})

    @app.post('/imports/{id}/confirm')
    async def confirm(request:Request,id:str):
        f=await form(request)
        if f.get('confirm')!='yes': raise HTTPException(422,'Bevestig dat je deze gegevens wilt importeren.')
        with connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            batch=batch_for(db,request,id)
            if batch['confirmed']: return go('/imports/'+id)
            payload=json.loads(batch['payload']); plan=plan_import(db,payload)
            if plan_hash(plan)!=json.loads(batch['summary'])['plan_hash']:
                raise HTTPException(409,'Gegevens zijn gewijzigd sinds het controleoverzicht. Upload opnieuw voor een actuele beoordeling.')
            created={}; summary={'contacts':0,'documents':0,'skipped_contacts':0,'skipped_documents':0}
            for c,p in zip(payload['contacts'],plan['contacts']):
                if p['status']=='conflict': summary['skipped_contacts']+=1; continue
                if p['status']=='new':
                    columns=('name','email','address','kvk','vat','contact','archived','phone')
                    target=db.execute('INSERT INTO customers(name,email,address,kvk,vat,contact,archived,phone,import_extra) VALUES(?,?,?,?,?,?,?,?,?)',
                                      (*(c[k] for k in columns),json.dumps(c['extra']))).lastrowid
                    created[p['target']]=target; summary['contacts']+=1
                else:
                    target=created.get(p['target'],p['target']); summary['skipped_contacts']+=1
                # Remember each original card/contact without overwriting the CRM data.
                extra=json.loads(db.execute('SELECT import_extra FROM customers WHERE id=?',(target,)).fetchone()[0])
                sources=extra.setdefault('importbronnen',[])
                source={'batch':id,'index':p['index'],'gegevens':c}
                source['hash']=fingerprint(c)
                if not any(item.get('hash')==source['hash'] for item in sources): sources.append(source)
                db.execute('UPDATE customers SET import_extra=? WHERE id=?',(json.dumps(extra),target))
                if c['external_id']:
                    db.execute("INSERT OR IGNORE INTO import_links VALUES('moneybird',?,?)",(c['external_id'],target))
            targets={c.get('customer_number'):created.get(p['target'],p['target']) for c,p in zip(payload['contacts'],plan['contacts']) if c.get('customer_number') and p['status']!='conflict'}
            for d,p in zip(payload['documents'],plan['documents']):
                if p['status']!='new': summary['skipped_documents']+=1; continue
                target=targets[d['contact_key']]
                snapshot={**d['customer'],'id':target}
                document_id=db.execute('INSERT INTO documents(kind,number,customer_id,customer,company,lines,total,status,date,due) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                       (d['kind'],d['number'],target,json.dumps(snapshot),json.dumps(d['company']),json.dumps(d['lines']),d['total'],d['status'],d['date'],d['due'])).lastrowid
                db.execute('INSERT INTO document_imports VALUES(?,?,?,?,?)',(document_id,id,fingerprint(d),d['original_status'],base64.b64decode(d['pdf'])))
                # Never let a future native document reuse an imported native-style number.
                match=re.fullmatch(r'([FO])(\d{4})-(\d{4,})',d['number'])
                if match:
                    kind='invoice' if match[1]=='F' else 'quote'
                    db.execute('INSERT INTO counters VALUES(?,?,?) ON CONFLICT(kind,year) DO UPDATE SET value=max(value,excluded.value)',(kind,match[2],int(match[3])))
                summary['documents']+=1
            # The original archive/PDFs remain; the bulky transient parsed payload can go.
            db.execute("UPDATE import_batches SET confirmed=1,summary=?,payload='{}' WHERE id=?",(json.dumps(summary),id))
        return go('/imports/'+id)

    @app.post('/imports/{id}/cancel')
    async def cancel(request:Request,id:str):
        await form(request)
        with connect(database) as db:
            batch=batch_for(db,request,id)
            if batch['confirmed']: raise HTTPException(409,'Een bevestigde import kan niet worden geannuleerd.')
            db.execute('DELETE FROM import_batches WHERE id=?',(id,))
        return go('/imports')

    @app.get('/imports/{id}/source')
    def source(request:Request,id:str):
        require(request)
        # Confirmed source archives are accessible to the admin in every session.
        with connect(database) as db:
            batch=db.execute('SELECT * FROM import_batches WHERE id=? AND confirmed=1',(id,)).fetchone()
        if not batch: raise HTTPException(404,'Bronbestand niet gevonden.')
        extension='zip' if batch['filename'].lower().endswith('.zip') else 'vcf'
        return Response(batch['original'],media_type='application/octet-stream',
                        headers={'Content-Disposition':f'attachment; filename="minibird-import-{id}.{extension}"'})
