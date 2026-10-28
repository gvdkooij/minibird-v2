import base64
from datetime import date
import io
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from app.db import connect, migrate
from app.importing import ImportProblem, MAX_UPLOAD, parse_upload, parse_vcards, checked_zip
from app.import_routes import plan_import
from app.main import create_app
from test_app import SECRET, ctx, setup, token, post

VCF=b'''BEGIN:VCARD
VERSION:3.0
ORG:Voorbeeld BV
FN:Jan Voorbeeld
N:Voorbeeld;Jan;;;
ADR:;;Straat 1;Utrecht;;1234 AB;NL
EMAIL:jan@example.nl
TEL:+31 123456789
END:VCARD
'''


def workbook(sheets):
    wb=Workbook(); wb.remove(wb.active)
    for name,rows in sheets.items():
        ws=wb.create_sheet(name)
        for row in rows: ws.append(row)
    out=io.BytesIO(); wb.save(out); return out.getvalue()


def zipped(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items(): z.writestr(name,data)
    return out.getvalue()


def export_files():
    from reportlab.pdfgen.canvas import Canvas
    out=io.BytesIO(); canvas=Canvas(out); canvas.drawString(40,800,'Test origineel'); canvas.save(); pdf=out.getvalue()
    ubl=f'''<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
<cbc:ID>2024-0001</cbc:ID><cbc:IssueDate>2024-01-01</cbc:IssueDate><cbc:DueDate>2024-01-15</cbc:DueDate><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
<cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Test Studio</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:StreetName>Gracht 2</cbc:StreetName></cac:PostalAddress></cac:Party></cac:AccountingSupplierParty>
<cac:AccountingCustomerParty><cac:Party><cac:PartyName><cbc:Name>Voorbeeld BV</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:StreetName>Straat 1</cbc:StreetName></cac:PostalAddress><cac:Contact><cbc:ElectronicMail>jan@example.nl</cbc:ElectronicMail></cac:Contact></cac:Party></cac:AccountingCustomerParty>
<cac:TaxTotal><cbc:TaxAmount>208.26</cbc:TaxAmount><cac:TaxSubtotal><cbc:TaxableAmount>991.74</cbc:TaxableAmount><cbc:TaxAmount>208.26</cbc:TaxAmount><cac:TaxCategory><cbc:Percent>21</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
<cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>991.74</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount>1200</cbc:TaxInclusiveAmount></cac:LegalMonetaryTotal>
<cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cbc:LineExtensionAmount>991.74</cbc:LineExtensionAmount><cac:Item><cbc:Description>Advies</cbc:Description><cac:ClassifiedTaxCategory><cbc:Percent>21</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item><cac:Price><cbc:PriceAmount>991.73553719</cbc:PriceAmount></cac:Price></cac:InvoiceLine></Invoice>'''
    return {
        'contacts/contacts.xlsx':workbook({'Contacten':[
            ['id','customer_id','company_name','firstname','lastname','email','address1','zipcode','city','country','phone','archived','tax_number','chamber_of_commerce'],
            ['contact-1','1','Voorbeeld BV','Jan','Voorbeeld','jan@example.nl','Straat 1','1234 AB','Utrecht','NL','0612345678','false','NL123','12345678']],
            'Contactpersonen':[['customer_id','firstname','lastname','email'],['1','Petra','Voorbeeld','petra@example.nl']]}),
        'sales_invoices/invoices.xlsx':workbook({'Facturen':[
            ['id','factuurnummer','status','factuurdatum','vervaldatum','klantnummer','valuta','totaalprijs inclusief btw'],
            ['invoice-1','2024-0001','paid','2024-01-01','2024-01-15','1','EUR',1200]]}),
        'sales_invoices_ubl_archive/2024-0001.xml':ubl,
        'sales_invoices_archive/2024/2024-0001.pdf':pdf,
        'estimates/quotes.xlsx':workbook({'Offertes':[
            ['id','offertenummer','status','offerte datum','vervaldatum','klantnummer','valuta','totaalprijs exclusief btw','totaalprijs inclusief btw'],
            ['quote-1','O2024-0020','late','2024-01-01','2024-02-01','1','EUR',100,121]]}),
        'estimates_details/quote-lines.xlsx':workbook({'Regels':[
            ['offertenummer','btw','totaalprijs exclusief btw inclusief korting','aantal (decimaal)','prijs','omschrijving'],
            ['O2024-0020','21% btw',100,1,100,'Ontwerp']]}),
        'estimates_archive/2024/O2024-0020.pdf':pdf,
        'LEESMIJ.txt':'Dit bestand is uitsluitend bronmateriaal, geen programma-instructie.',
        'balance_sheet/report.xlsx':workbook({'Balans':[['Rapport'],[100]]}),
    }


def upload(c,content=VCF,name='contacts.vcf'):
    csrf=token(c,'/imports')
    return c.post('/imports/preview',data={'csrf':csrf},files={'file':(name,content)},follow_redirects=False)


def confirm(c,url):
    return post(c,url+'/confirm',{'confirm':'yes'},url)


def test_vcard_fold_escape_and_extra_fields():
    cards=parse_vcards(b'BEGIN:VCARD\r\nVERSION:3.0\r\nORG:Bedrijf\\; Test\r\nFN:Jan\r\nEMAIL:jan@example.nl\r\nADR:;;Straat\\; 1;Utrecht;;1234 AB;NL\r\nNOTE:Lange\r\n  tekst\r\nEND:VCARD')['contacts']
    assert cards[0]['name']=='Bedrijf; Test'
    assert 'Straat; 1' in cards[0]['address']
    assert cards[0]['extra']['vcard']['NOTE']==['Lange tekst']
    multi=VCF.replace(b'jan@example.nl',b'jan@example.nl; ander@example.nl')
    result=parse_vcards(multi)['contacts'][0]
    assert result['email']=='jan@example.nl' and result['warnings']
    invalid=VCF.replace(b'jan@example.nl',b'geen email')
    assert parse_vcards(invalid)['contacts'][0]['email']==''


def test_preview_cancel_confirm_and_repeat_upload(ctx):
    c,db=ctx;setup(c)
    r=upload(c);assert r.status_code==303,r.text
    url=r.headers['location']
    assert 'Voorbeeld BV' in c.get(url).text
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==0
    assert post(c,url+'/confirm',page=url).status_code==422
    assert confirm(c,url).status_code==303
    assert confirm(c,url).status_code==303
    assert '1 nieuwe klanten' in c.get(url).text
    r=upload(c);other=r.headers['location'];confirm(c,other)
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1
        customer=conn.execute('SELECT * FROM customers').fetchone()
        assert customer['phone']=='+31 123456789'
        assert len(json.loads(customer['import_extra'])['importbronnen'])==1
    assert 'Oorspronkelijke importgegevens' in c.get('/customers/1').text
    r=upload(c);cancelled=r.headers['location']
    assert post(c,cancelled+'/cancel',page=cancelled).status_code==303
    assert c.get(cancelled).status_code==404


def test_moneybird_import_originals_snapshots_and_idempotency(ctx):
    c,db=ctx;setup(c);files=export_files();raw=zipped(files)
    r=upload(c,raw,'moneybird.zip');assert r.status_code==303,r.text
    url=r.headers['location']; html=c.get(url).text
    assert '2024-0001' in html and 'alleen bewaard in bronarchief' in html
    assert confirm(c,url).status_code==303
    assert c.get(url+'/source').content==raw
    with connect(db) as conn:
        docs=conn.execute('SELECT * FROM documents ORDER BY id').fetchall()
        assert len(docs)==2 and docs[0]['number']=='2024-0001' and docs[0]['status']=='paid'
        assert docs[0]['total']==120000
        line=json.loads(docs[0]['lines'])[0]
        assert line['net']==99174 and line['vat']==20826
        assert conn.execute('SELECT value FROM counters WHERE kind="quote" AND year="2024"').fetchone()[0]==20
        assert 'Petra' in conn.execute('SELECT import_extra FROM customers').fetchone()[0]
    invoice=f'/documents/{docs[0]["id"]}'
    assert c.get(invoice+'/pdf').content==files['sales_invoices_archive/2024/2024-0001.pdf']
    assert 'alleen-lezen' in c.get(invoice).text
    assert post(c,invoice+'/email').status_code==409
    assert post(c,invoice+'/delete').status_code==409
    r=upload(c,raw,'another-name.zip');assert r.status_code==303
    assert 'Al aanwezig' in c.get(r.headers['location']).text
    confirm(c,r.headers['location'])
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM documents').fetchone()[0]==2
    restarted=TestClient(create_app(db,SECRET,False))
    post(restarted,'/login',{'email':'admin@example.nl','password':'correct horse battery staple'},'/login')
    assert restarted.get(invoice+'/pdf').content==files['sales_invoices_archive/2024/2024-0001.pdf']
    assert restarted.get(url).status_code==200
    assert restarted.get(url+'/source').content==raw


def test_vcard_then_moneybird_existing_contact_not_overwritten(ctx):
    c,db=ctx;setup(c)
    r=upload(c);confirm(c,r.headers['location'])
    r=upload(c,zipped(export_files()),'export.zip');assert r.status_code==303,r.text
    confirm(c,r.headers['location'])
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM documents').fetchone()[0]==2
        # Original vCard phone retained, richer ZIP fields kept separately.
        assert conn.execute('SELECT phone FROM customers').fetchone()[0]=='+31 123456789'
        assert conn.execute('SELECT count(*) FROM import_links').fetchone()[0]==1


def test_auth_csrf_pending_ownership_and_stale_preview(ctx):
    c,db=ctx
    assert c.post('/imports/preview',files={'file':('a.vcf',VCF)},follow_redirects=False).status_code==303
    setup(c)
    assert c.post('/imports/preview',files={'file':('a.vcf',VCF)}).status_code==403
    r=upload(c);url=r.headers['location']
    other=TestClient(create_app(db,SECRET,False))
    post(other,'/login',{'email':'admin@example.nl','password':'correct horse battery staple'},'/login')
    assert other.get(url).status_code==404
    post(c,'/customers',{'name':'Voorbeeld BV','email':'jan@example.nl','address':'Straat 1'})
    assert confirm(c,url).status_code==409
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1


def test_conflicting_documents_and_ambiguous_contacts(ctx):
    c,db=ctx;setup(c);raw=zipped(export_files())
    r=upload(c,raw,'export.zip');confirm(c,r.headers['location'])
    modified=export_files()
    modified['sales_invoices_archive/2024/2024-0001.pdf']+=b'\nchanged'
    r=upload(c,zipped(modified),'changed.zip');html=c.get(r.headers['location']).text
    assert 'Het nummer bestaat met andere gegevens' in html
    confirm(c,r.headers['location'])
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM documents').fetchone()[0]==2
    v=VCF.replace(b'jan@example.nl',b'ander@example.nl')
    r=upload(c,v);assert 'Handmatig beoordelen' in c.get(r.headers['location']).text


@pytest.mark.parametrize('data,name',[(b'','x.vcf'),(b'hello','x.vcf'),(b'BEGIN:VCARD\nFN:x','x.vcf'),(b'abc','x.zip'),(VCF,'x.pdf')])
def test_invalid_uploads(data,name):
    with pytest.raises(ImportProblem): parse_upload(name,data)


def test_archive_path_bomb_xml_and_amount_mismatch(ctx):
    for raw in [zipped({'../outside':'x'}),zipped({'/absolute':'x'}),zipped({'safe':'0'*1000000})]:
        with pytest.raises(ImportProblem): checked_zip(raw)
    files=export_files();xml_name='sales_invoices_ubl_archive/2024-0001.xml'
    files[xml_name]=files[xml_name].replace('<cbc:TaxInclusiveAmount>1200','<cbc:TaxInclusiveAmount>9999')
    with pytest.raises(ImportProblem): parse_upload('x.zip',zipped(files))
    files=export_files();files[xml_name]='<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+files[xml_name]
    with pytest.raises(ImportProblem): parse_upload('x.zip',zipped(files))
    c,db=ctx;setup(c)
    assert upload(c,b'x'*(MAX_UPLOAD+1)).status_code in (413,422)
    assert not Path('/tmp/outside').exists()


def test_migrate_version_one_preserves_existing_customer(tmp_path):
    import sqlite3
    from app.db import SCHEMA
    path=tmp_path/'old.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute('INSERT INTO customers(name,email,address,kvk,vat,contact) VALUES(?,?,?,?,?,?)',('Oud','a@example.nl','Adres','','',''))
        db.execute('PRAGMA user_version=1')
    migrate(path);migrate(path)
    with connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==2
        assert db.execute('SELECT name,phone FROM customers').fetchone()[:]==('Oud','')


def test_shared_email_different_company_stays_separate(ctx):
    c,db=ctx;setup(c)
    two=VCF+VCF.replace(b'Voorbeeld BV',b'Ander Bedrijf BV')
    r=upload(c,two);confirm(c,r.headers['location'])
    with connect(db) as conn: assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==2


def test_zip_transaction_rolls_back_on_storage_failure(ctx):
    c,db=ctx;setup(c)
    r=upload(c,zipped(export_files()),'export.zip');url=r.headers['location']
    with connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_document BEFORE INSERT ON document_imports BEGIN SELECT RAISE(ABORT,'test failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError): confirm(c,url)
    with connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM documents').fetchone()[0]==0
        assert conn.execute('SELECT confirmed FROM import_batches').fetchone()[0]==0


def test_import_escapes_untrusted_text(ctx):
    c,db=ctx;setup(c)
    vcf=VCF.replace(b'Voorbeeld BV',b'<script>alert(1)</script>')
    r=upload(c,vcf);html=c.get(r.headers['location']).text
    assert '&lt;script&gt;' in html and '<script>alert' not in html
