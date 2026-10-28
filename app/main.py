import base64
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import smtplib
import ssl
import time
from datetime import date, timedelta
from email.message import EmailMessage
from html import escape

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.pdfgen import canvas
from .sessions import ServerSessionMiddleware
from .db import connect, migrate
from .domain import calculate

PASSWORDS = PasswordHasher()
LOG = logging.getLogger('minibird')
BASE = Path(__file__).parent


def create_app(database=None, secret=None, secure=None):
    database = database or os.getenv('MINIBIRD_DB','data/minibird.sqlite')
    secret = secret or os.getenv('MINIBIRD_SECRET')
    if not secret or len(secret)<32:
        raise RuntimeError('Stel MINIBIRD_SECRET in op minimaal 32 willekeurige tekens')
    secure = secure if secure is not None else os.getenv('MINIBIRD_SECURE','true').lower() == 'true'
    migrate(database)
    os.chmod(database,0o600)
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(ServerSessionMiddleware, database=database, secret_key=secret, secure=secure)
    app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')
    templates = Jinja2Templates(directory=BASE/'templates')
    templates.env.filters['money'] = lambda n: f'€ {n/100:,.2f}'.replace(',','X').replace('.',',').replace('X','.')

    def settings(db):
        return json.loads(db.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])

    def render(request, page, **context):
        request.session.setdefault('csrf',secrets.token_urlsafe(32))
        return templates.TemplateResponse(request=request,name=page,context=dict(csrf=request.session['csrf'],logged=bool(request.session.get('admin')),**context))

    def go(path):
        return RedirectResponse(path,303)

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({'X-MiniBird-Response':'1','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin','Content-Security-Policy':"default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",'Cache-Control':'no-store'})
        if secure: response.headers['Strict-Transport-Security']='max-age=31536000'
        LOG.info(json.dumps({'event':'http','method':request.method,'status':response.status_code}))
        return response

    @app.exception_handler(HTTPException)
    async def error(request, exc):
        if 'application/json' in request.headers.get('accept',''):
            body={'detail':exc.detail}
            if exc.status_code==401: body['code']=getattr(request.state,'auth_failure','MB-AUTH-REQUIRED')
            return JSONResponse(body,status_code=exc.status_code)
        if exc.status_code==401: return go('/login')
        return HTMLResponse(templates.env.get_template('error.html').render(csrf=request.session.get('csrf',''),logged=bool(request.session.get('admin')),message=exc.detail,code=exc.status_code),status_code=exc.status_code)

    def require(request):
        if not request.session.get('admin'):
            if not request.cookies.get('minibird_session'): request.state.auth_failure='MB-COOKIE-MISSING'
            elif request.scope.get('minibird_auth_state')=='invalid': request.state.auth_failure='MB-COOKIE-INVALID'
            else: request.state.auth_failure='MB-AUTH-REQUIRED'
            raise HTTPException(401,'Log eerst in')

    async def form(request, auth=True):
        if auth: require(request)
        f=await request.form(max_fields=600)
        if not request.session.get('csrf') or not secrets.compare_digest(str(f.get('csrf','')).encode(),request.session['csrf'].encode()):
            raise HTTPException(403,'Ongeldige beveiligingscode. Vernieuw de pagina.')
        return f

    def text(f,key,required=False,limit=500):
        s=str(f.get(key,'')).strip()
        if len(s)>limit or (required and not s): raise HTTPException(422,'Controleer veld: '+key)
        return s

    def email(value):
        if value and (not re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+',value) or len(value)>254):
            raise HTTPException(422,'Ongeldig e-mailadres')
        return value

    @app.get('/health')
    def health():
        with connect(database) as db: db.execute('SELECT 1').fetchone()
        return {'status':'ok'}

    @app.get('/setup',response_class=HTMLResponse)
    def setup(request:Request):
        with connect(database) as db:
            if db.execute('SELECT 1 FROM admin').fetchone(): return go('/login')
        return render(request,'auth.html',setup=True)

    @app.post('/setup')
    async def setup_post(request:Request):
        f=await form(request,False)
        address=email(text(f,'email',True))
        password=text(f,'password',True,1024)
        if len(password)<12: raise HTTPException(422,'Gebruik minimaal 12 tekens')
        with connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM admin').fetchone(): raise HTTPException(409,'Beheerder bestaat al')
            db.execute('INSERT INTO admin VALUES(1,?,?)',(address,PASSWORDS.hash(password)))
        request.session.clear()
        request.session['admin']=True
        return go('/')

    @app.get('/login',response_class=HTMLResponse)
    def login(request:Request):
        with connect(database) as db:
            if not db.execute('SELECT 1 FROM admin').fetchone(): return go('/setup')
        return render(request,'auth.html',setup=False)

    @app.post('/login')
    async def login_post(request:Request):
        f=await form(request,False)
        address=request.client.host
        with connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE time<?',(time.time()-900,))
            if db.execute('SELECT count(*) FROM attempts WHERE address=?',(address,)).fetchone()[0]>=5:
                raise HTTPException(429,'Te veel pogingen. Wacht 15 minuten.')
            db.execute('INSERT INTO attempts VALUES(?,?)',(address,time.time()))
            user=db.execute('SELECT * FROM admin').fetchone()
        valid=False
        if user:
            try: valid=PASSWORDS.verify(user['password'],str(f.get('password',''))) and secrets.compare_digest(user['email'].encode(),str(f.get('email','')).encode())
            except VerificationError: pass
        if not valid: raise HTTPException(400,'Onjuiste inloggegevens')
        with connect(database) as db: db.execute('DELETE FROM attempts WHERE address=?',(address,))
        request.session.clear()
        request.session['admin']=True
        return go('/')

    @app.post('/logout')
    async def logout(request:Request):
        await form(request)
        request.session.clear()
        return go('/login')

    @app.get('/',response_class=HTMLResponse)
    def dashboard(request:Request):
        require(request)
        with connect(database) as db:
            docs=[dict(x) for x in db.execute('SELECT * FROM documents ORDER BY id DESC')]
        for d in docs: d['status']=state(d)
        return render(request,'dashboard.html',docs=docs,open_total=sum(d['total'] for d in docs if d['kind']=='invoice' and d['status'] in ('sent','overdue')),paid_total=sum(d['total'] for d in docs if d['kind']=='invoice' and d['status']=='paid'))

    @app.get('/customers',response_class=HTMLResponse)
    def customers(request:Request,q:str='',archived:str='0'):
        require(request)
        with connect(database) as db:
            rows=db.execute('SELECT * FROM customers WHERE (name LIKE ? OR email LIKE ?) AND archived=? ORDER BY name',('%'+q+'%','%'+q+'%',int(archived=='1'))).fetchall()
        return render(request,'customers.html',customers=rows,q=q,archived=archived)

    @app.get('/customers/{id}',response_class=HTMLResponse)
    def customer_edit(request:Request,id:int):
        require(request)
        with connect(database) as db: customer=db.execute('SELECT * FROM customers WHERE id=?',(id,)).fetchone()
        if not customer: raise HTTPException(404,'Klant niet gevonden')
        return render(request,'customer.html',customer=customer,extra=json.loads(customer['import_extra']))

    @app.post('/customers')
    async def customer_save(request:Request):
        f=await form(request)
        values=[text(f,'name',True),email(text(f,'email')),text(f,'address',True),text(f,'kvk'),text(f,'vat'),text(f,'contact'),text(f,'phone')]
        with connect(database) as db:
            if f.get('id'):
                try: customer_id=int(f['id'])
                except ValueError: raise HTTPException(422,'Ongeldig klantnummer')
                if not db.execute('SELECT 1 FROM customers WHERE id=?',(customer_id,)).fetchone(): raise HTTPException(404,'Klant niet gevonden')
                db.execute('UPDATE customers SET name=?,email=?,address=?,kvk=?,vat=?,contact=?,phone=? WHERE id=?',(*values,customer_id))
            else: db.execute('INSERT INTO customers(name,email,address,kvk,vat,contact,phone) VALUES(?,?,?,?,?,?,?)',values)
        return go('/customers')

    @app.post('/customers/{id}/{action}')
    async def customer_action(request:Request,id:int,action:str):
        await form(request)
        with connect(database) as db:
            if action in ('archive','restore'): db.execute('UPDATE customers SET archived=? WHERE id=?',(int(action=='archive'),id))
            elif action=='delete':
                if db.execute('SELECT 1 FROM documents WHERE customer_id=?',(id,)).fetchone() or db.execute('SELECT 1 FROM import_links WHERE customer_id=?',(id,)).fetchone(): raise HTTPException(409,'Deze klant heeft documenten. Archiveer de klant.')
                db.execute('DELETE FROM customers WHERE id=?',(id,))
            else: raise HTTPException(404,'Onbekende actie')
        return go('/customers')

    @app.get('/settings',response_class=HTMLResponse)
    def settings_page(request:Request):
        require(request)
        with connect(database) as db: s=settings(db)
        s.pop('smtp_password',None)
        return render(request,'settings.html',s=s)

    @app.post('/settings')
    async def settings_save(request:Request):
        f=await form(request)
        with connect(database) as db:
            s=settings(db)
            for key in ('name','address','kvk','vat','iban','smtp_host','smtp_user','smtp_from'):
                s[key]=text(f,key,key=='name')
            email(s['smtp_from'])
            try: port=int(f.get('smtp_port') or 587)
            except ValueError: raise HTTPException(422,'Ongeldige SMTP-poort')
            if not 1<=port<=65535: raise HTTPException(422,'Ongeldige SMTP-poort')
            s['smtp_port']=port
            if f.get('smtp_password'): s['smtp_password']=cipher.encrypt(text(f,'smtp_password',limit=1024).encode()).decode()
            if f.get('clear_password'): s.pop('smtp_password',None)
            db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(s),))
        return go('/settings')

    def smtp(s,message=None):
        if not s.get('smtp_host') or not s.get('smtp_from'): raise HTTPException(422,'Vul eerst SMTP-server en afzender in')
        try:
            with smtplib.SMTP(s['smtp_host'],s.get('smtp_port',587),timeout=15) as server:
                server.ehlo(); server.starttls(context=ssl.create_default_context()); server.ehlo()
                if s.get('smtp_user'): server.login(s['smtp_user'],cipher.decrypt(s.get('smtp_password','').encode()).decode())
                if message: server.send_message(message)
        except Exception:
            LOG.warning('{"event":"smtp_failure"}')
            raise HTTPException(502,'SMTP-verbinding mislukt. Controleer instellingen en bereikbaarheid.') from None

    @app.post('/settings/test')
    async def smtp_test(request:Request):
        await form(request)
        with connect(database) as db: s=settings(db)
        smtp(s)
        return render(request,'message.html',message='SMTP-verbinding geslaagd. Er is geen e-mail verstuurd.')

    def state(d):
        return 'overdue' if d['status']=='sent' and d['due']<date.today().isoformat() else d['status']

    def document(db,id):
        row=db.execute('SELECT * FROM documents WHERE id=?',(id,)).fetchone()
        if not row: raise HTTPException(404,'Document niet gevonden')
        d=dict(row)
        for key in ('customer','company','lines'): d[key]=json.loads(d[key])
        d['display_status']=state(d)
        imported=db.execute('SELECT batch_id,original_status FROM document_imports WHERE document_id=?',(id,)).fetchone()
        d['imported']=dict(imported) if imported else None
        return d

    def insert(db,kind,customer,company,lines,due,source=None):
        year=str(date.today().year)
        db.execute('INSERT INTO counters VALUES(?,?,1) ON CONFLICT(kind,year) DO UPDATE SET value=value+1',(kind,year))
        n=db.execute('SELECT value FROM counters WHERE kind=? AND year=?',(kind,year)).fetchone()[0]
        number=f'{"F" if kind=="invoice" else "O"}{year}-{n:04d}'
        return db.execute('INSERT INTO documents(kind,number,customer_id,customer,company,lines,total,date,due,source_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(kind,number,customer['id'],json.dumps(customer),json.dumps(company),json.dumps(lines),sum(x['net']+x['vat'] for x in lines),date.today().isoformat(),due,source)).lastrowid

    @app.get('/documents',response_class=HTMLResponse)
    def documents(request:Request,kind:str='invoice',q:str='',status:str=''):
        require(request)
        with connect(database) as db:
            docs=[dict(x) for x in db.execute('SELECT * FROM documents WHERE kind=? AND (number LIKE ? OR customer LIKE ?) ORDER BY id DESC',(kind,'%'+q+'%','%'+q+'%'))]
        for d in docs: d['status']=state(d)
        if status: docs=[d for d in docs if d['status']==status]
        return render(request,'documents.html',docs=docs,kind=kind,q=q,status=status)

    @app.get('/documents/new',response_class=HTMLResponse)
    def new_document(request:Request,kind:str='invoice'):
        require(request)
        if kind not in ('invoice','quote'): raise HTTPException(422,'Ongeldig type')
        with connect(database) as db: customers=db.execute('SELECT * FROM customers WHERE archived=0 ORDER BY name').fetchall()
        return render(request,'new.html',kind=kind,customers=customers,due=(date.today()+timedelta(days=30)).isoformat())

    @app.post('/documents')
    async def create_document(request:Request):
        f=await form(request)
        kind=text(f,'kind')
        if kind not in ('invoice','quote'): raise HTTPException(422,'Ongeldig type')
        try:
            lines=calculate(*(f.getlist(k) for k in ('description','quantity','price','rate')))
            due=date.fromisoformat(str(f.get('due'))).isoformat()
            customer_id=int(f.get('customer_id','0'))
        except (ValueError,TypeError) as exc: raise HTTPException(422,str(exc))
        with connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            c=db.execute('SELECT * FROM customers WHERE id=? AND archived=0',(customer_id,)).fetchone()
            if not c: raise HTTPException(422,'Kies een actieve klant')
            s=settings(db)
            if not s.get('name') or not s.get('address'): raise HTTPException(422,'Vul eerst bedrijfsnaam en adres in bij Instellingen')
            company={k:s.get(k,'') for k in ('name','address','kvk','vat','iban')}
            id=insert(db,kind,dict(c),company,lines,due)
        return go(f'/documents/{id}')

    @app.get('/documents/{id}',response_class=HTMLResponse)
    def detail(request:Request,id:int):
        require(request)
        with connect(database) as db: d=document(db,id)
        return render(request,'detail.html',d=d)

    def pdf(d):
        out=io.BytesIO(); p=canvas.Canvas(out,pagesize=(595,842))
        y=800
        rows=[d['company'].get('name',''),d['company'].get('address',''),'KvK: '+d['company'].get('kvk','')+' | Btw: '+d['company'].get('vat',''),'IBAN: '+d['company'].get('iban',''),'','FACTUUR' if d['kind']=='invoice' else 'OFFERTE',d['number'],'Datum: '+d['date']+' | Vervaldatum: '+d['due'],'Status: '+d['display_status'],'',d['customer']['name'],d['customer']['address'],'']
        for l in d['lines']:
            rows += [l['description'],f"{l['quantity']} x EUR {l['price']} | btw {l['rate']}% | EUR {(l['net']+l['vat'])/100:.2f}"]
        rows += ['',f"Exclusief btw: EUR {sum(l['net'] for l in d['lines'])/100:.2f}",f"Btw: EUR {sum(l['vat'] for l in d['lines'])/100:.2f}",f"Totaal: EUR {d['total']/100:.2f}"]
        for row in rows:
            for part in str(row).splitlines() or ['']:
                for i in range(0,max(1,len(part)),85):
                    if y<50: p.showPage(); y=800
                    p.setFont('Helvetica',11); p.drawString(40,y,part[i:i+85]); y-=17
        p.save(); return out.getvalue()

    @app.get('/documents/{id}/pdf')
    def download(request:Request,id:int):
        require(request)
        with connect(database) as db: d=document(db,id)
        with connect(database) as db:
            original=db.execute('SELECT pdf FROM document_imports WHERE document_id=?',(id,)).fetchone()
        filename=re.sub(r'[^A-Za-z0-9_.-]', '_', d['number']).lstrip('.') or 'document'
        return Response(original['pdf'] if original else pdf(d),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{filename}.pdf"'})

    @app.post('/documents/{id}/{action}')
    async def action(request:Request,id:int,action:str):
        await form(request)
        with connect(database) as db:
            db.execute('BEGIN IMMEDIATE')
            d=document(db,id)
            if d['imported']: raise HTTPException(409,'Geïmporteerde documenten zijn alleen-lezen. Maak voor nieuwe acties een nieuw document.')
            if action=='delete' and d['status']=='draft':
                db.execute('DELETE FROM documents WHERE id=?',(id,)); return go('/documents?kind='+d['kind'])
            if action=='issue' and d['status']=='draft': new='sent'
            elif action=='accept' and d['kind']=='quote' and d['status']=='sent': new='accepted'
            elif action=='paid' and d['kind']=='invoice' and d['status']=='sent': new='paid'
            elif action=='convert' and d['kind']=='quote' and d['status']=='accepted':
                old=db.execute('SELECT id FROM documents WHERE source_id=?',(id,)).fetchone()
                target=old[0] if old else insert(db,'invoice',d['customer'],d['company'],d['lines'],(date.today()+timedelta(days=30)).isoformat(),id)
                return go(f'/documents/{target}')
            elif action=='email' and d['status'] in ('draft','sent'):
                recipient=email(d['customer']['email'])
                if not recipient: raise HTTPException(422,'Klant heeft geen e-mailadres')
                s=settings(db)
                msg=EmailMessage(); msg['From']=email(s.get('smtp_from','')); msg['To']=recipient; msg['Subject']=('Factuur ' if d['kind']=='invoice' else 'Offerte ')+d['number']
                msg.set_content(f"Beste {d['customer']['name']},\n\nBijgevoegd ontvangt u document {d['number']}.\n\nMet vriendelijke groet,\n{d['company']['name']}")
                d['display_status']='sent'
                msg.add_attachment(pdf(d),maintype='application',subtype='pdf',filename=d['number']+'.pdf')
                smtp(s,msg); new='sent'
            else: raise HTTPException(409,'Deze actie is niet toegestaan in de huidige status')
            db.execute('UPDATE documents SET status=? WHERE id=?',(new,id))
        return go(f'/documents/{id}')
    from .import_routes import register_import_routes
    register_import_routes(app,database,render,require,form,go)
    return app
