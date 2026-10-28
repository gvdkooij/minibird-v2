"""Optional real Chromium workflow. Run: .venv/bin/python tests/browser_smoke.py"""
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    env={**os.environ,'MINIBIRD_DB':str(Path(tmp)/'browser.sqlite'),'MINIBIRD_SECRET':secrets.token_urlsafe(48),'MINIBIRD_SECURE':'false'}
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        url=f'http://127.0.0.1:{port}'
        for _ in range(100):
            try:
                with urllib.request.urlopen(url+'/health',timeout=1) as response:
                    assert response.status==200
                break
            except OSError: time.sleep(.1)
        else: raise AssertionError('Server start mislukt')
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or shutil.which('chromium') or p.chromium.executable_path,headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'/setup')
            page.get_by_label('E-mailadres',exact=True).fill('browser@example.nl')
            password=secrets.token_urlsafe(24)
            page.get_by_label('Wachtwoord',exact=True).fill(password)
            page.get_by_role('button',name='Beheerder aanmaken').click()
            page.get_by_role('link',name='Instellingen',exact=True).click()
            page.get_by_label('Bedrijfsnaam',exact=True).fill('Studio Noord')
            page.get_by_label('Adres',exact=True).fill('Gracht 1, Utrecht')
            page.get_by_role('button',name='Instellingen opslaan').click()
            page.get_by_role('link',name='Klanten',exact=True).click()
            page.get_by_label('Bedrijfsnaam / naam').fill('Voorbeeld BV')
            page.get_by_label('E-mailadres',exact=True).fill('klant@example.nl')
            page.get_by_label('Adres',exact=True).fill('Markt 2, Amsterdam')
            page.get_by_role('button',name='Klant opslaan').click()
            page.get_by_role('link',name='Offertes',exact=True).click()
            page.get_by_role('link',name='+ Nieuwe offerte').click()
            page.locator('[name=customer_id]').select_option(label='Voorbeeld BV')
            page.get_by_label('Omschrijving',exact=True).fill('Ontwerp en advies')
            page.get_by_label('Prijs excl. btw (€)').fill('100')
            page.get_by_role('button',name='+ Regel toevoegen').click()
            page.locator('[name=description]').nth(1).fill('Ondersteuning')
            page.locator('[name=price]').nth(1).fill('50')
            page.get_by_role('button',name='Concept opslaan').click()
            assert '€ 181,50' in page.inner_text('main')
            page.get_by_role('button',name='Markeer als verzonden').click()
            page.get_by_role('button',name='Markeer als geaccepteerd').click()
            page.get_by_role('button',name='Omzetten naar factuur').click()
            assert page.locator('.eyebrow').first.inner_text()=='FACTUUR'
            with page.expect_download() as download:
                page.get_by_role('link',name='PDF downloaden').click()
            assert download.value.suggested_filename.endswith('.pdf')
            assert Path(download.value.path()).read_bytes().startswith(b'%PDF-')
            page.get_by_role('button',name='Markeer als verzonden').click()
            page.get_by_role('button',name='Markeer als betaald').click()
            assert 'Betaald' in page.inner_text('main')
            page.get_by_role('link',name='Overzicht',exact=True).click()
            page.screenshot(path='/tmp/minibird-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path='/tmp/minibird-mobile.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.get_by_role('button',name='Uitloggen').click()
            page.get_by_label('E-mailadres',exact=True).fill('browser@example.nl')
            page.get_by_label('Wachtwoord',exact=True).fill(password)
            page.get_by_role('button',name='Inloggen',exact=True).click()
            assert 'Goed overzicht' in page.inner_text('main')
            assert not errors,errors
            browser.close()
        print('Browser smoke: setup, settings, customer, multi-line quote, conversion, PDF, payment, responsive dashboard, logout/login PASSED')
    finally:
        process.terminate();process.wait(timeout=10)
