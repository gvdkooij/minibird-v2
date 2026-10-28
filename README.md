# MiniBird v2
Nederlandstalige facturatie voor één bedrijf en één beheerder. Python 3.12+, FastAPI, SQLite en server-rendered HTML; geen Node of Docker nodig. Gericht op Ubuntu 24.04 met 1 vCPU en 1 GB RAM.

## Gratis uitproberen in GitHub Codespaces

[Open MiniBird in Codespaces](https://codespaces.new/gvdkooij/minibird-v2?ref=codespaces-setup)

1. Log in bij GitHub, kies branch **codespaces-setup** en maak de Codespace aan. Gebruik de standaardmachine met 2 cores. GitHub toont de beschikbare gratis quota en eventuele kosten; je hoeft voor deze app geen betaalde opties te kiezen.
2. Wacht tot de installatie is afgerond. De app start automatisch. Open in het tabblad **Ports** de browserlink van poort **8000**. Kies **Open in Browser**, niet de ingesloten editorpreview. Laat de zichtbaarheid op **Private**; GitHub vraagt om je eigen login. Er wordt geen publiek toegankelijke demo gemaakt.
3. Maak in MiniBird je eigen beheerder aan en vul daarna je bedrijfsgegevens en een testklant in. Gebruik fictieve gegevens om uit te proberen. Je kiest zelf je wachtwoord; er zijn geen standaardinloggegevens.

De browserlink gebruikt HTTPS en MiniBird gebruikt Secure-cookies. De interne server blijft op 127.0.0.1 draaien. Database en sessiesleutel staan in de genegeerde map `data/` onder de checkout. Ze blijven behouden bij stoppen/starten en een normale containerrebuild van dezelfde Codespace. **Bij verwijderen van de Codespace verdwijnen ze**: maak vooraf een backup en download die samen met de sleutel als je gegevens wilt bewaren. Zet geheimen of financiële gegevens nooit in Git.

Na een herstart start de app opnieuw automatisch. Indien nodig: `.venv/bin/python .devcontainer/start.py`. Startfouten staan in `data/codespaces.log`. Sluit na het testen de Codespace via GitHub met **Stop codespace**, zodat geen onnodige rekentijd wordt gebruikt. Een Codespace kan bij inactiviteit vanzelf stoppen; dit is een proefomgeving, geen permanente hosting. Gratis gebruik is afhankelijk van je GitHub-account en resterende quota.

## Snel lokaal starten
```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sh scripts/dev.sh
```
Open lokaal poort 8000. De server bindt uitsluitend aan 127.0.0.1. Stel de eerste beheerder in met een wachtwoord van minstens 12 tekens. Op een VPS: gebruik eerst een SSH-tunnel (`ssh -L 8000:127.0.0.1:8000 gebruiker@server`) en voer de setup uit voordat toegang voor andere gebruikers mogelijk wordt. Development gebruikt HTTP-cookies; uitsluitend lokaal gebruiken.

Vul bedrijfsnaam/adres in bij Instellingen, voeg een klant toe en maak een offerte of factuur met één of meer regels. Elke regel heeft hoeveelheid, prijs exclusief btw en 0%, 9% of 21% btw. Bedragen worden per regel half-up afgerond naar centen; btw wordt daarna per regel afgerond. Offertes: concept → verzonden → geaccepteerd → één gekoppelde conceptfactuur. Facturen: concept → verzonden → betaald. Verzonden facturen na de vervaldatum worden als verlopen weergegeven. Registratie van betaling is handmatig, geen bankkoppeling. PDF, zoeken, filteren en klantenarchief zijn beschikbaar.

Concepten mogen worden verwijderd en opnieuw aangemaakt; hun nummers worden nooit hergebruikt. Ook concepten krijgen dus een nummer. Het programma biedt bewust geen inline documentbewerking. Bedrijfs- en klantgegevens worden onveranderlijk in het document opgeslagen.

## vCard en Moneybird-jaarexport importeren

Open **Importeren** in het menu. Upload een `.vcf` (UTF-8 vCard) of de originele Moneybird-jaarexport als `.zip` (maximaal 50 MB). De browser uploadt het bestand met voortgang in delen van 512 KiB, zodat een proxy niet één groot verzoek hoeft te accepteren. Elk deel vereist een geldige beheerderssessie en CSRF-code. Uploaddelen zijn aan de sessie gebonden, worden op volgorde en grootte gecontroleerd en na het samenstellen verwijderd. Onvolledige uploads vervallen na een uur en worden bij volgende uploads opgeruimd. Zonder JavaScript blijft de gewone formulierupload beschikbaar, afhankelijk van de limiet van de proxy. De app bewaart de upload tijdelijk om een controleoverzicht te tonen. Pas na het aanvinken en definitief bevestigen worden klanten en historische documenten toegevoegd. Annuleren verwijdert de tijdelijke upload. Oude onbevestigde uploads worden bij een volgende upload na een uur opgeruimd. Bronbestanden en originele PDF’s van bevestigde imports blijven bewaard in de database en gaan mee in de SQLite-backup.

- **vCard:** naam/bedrijf, contactpersoon, adres, eerste geldige e-mailadres en telefoonnummer. Meerdere of ongeldige e-mailadressen krijgen een waarschuwing; het oorspronkelijke veld en alle aanvullende velden blijven bewaard.
- **Moneybird ZIP:** contacten uit `contacts/*.xlsx` (Contacten en Contactpersonen), verkoopfacturen uit `sales_invoices/*.xlsx` met UBL uit `sales_invoices_ubl_archive/`, en offertes uit `estimates/*.xlsx` met regels uit `estimates_details/`. Originele PDF’s komen uit de bijbehorende archiefmappen of, bij facturen, uit de UBL-bijlage. Er worden geen PDF’s met OCR geïnterpreteerd. Voor offertes zijn de afzendergegevens uit UBL-facturen in dezelfde export nodig. Moneybird-concepten zoals `Concept #3` houden hun bronnummer en blijven ongedateerd wanneer de export geen offertedatum bevat; de oorspronkelijke `draft_3.pdf` blijft beschikbaar. Downloadnamen worden afzonderlijk veilig gemaakt.
- Nummers, historische datums, bronstatussen, bedrijfs-/klantsnapshots en bedragen blijven behouden. Alleen EUR en 0/9/21% btw worden ondersteund, inclusief UBL-categorieën voor geen btw/vrijstelling (O/E/Z). Een ontbrekend percentage wordt uitsluitend bij zo’n expliciete nul-/vrijstellingscategorie als nul behandeld. Het onderscheid tussen geen btw en vrijgesteld blijft zichtbaar. De import controleert regels, btw-groepen en totalen; afrondingscenten uit UBL worden behouden. Afwijkingen die niet aansluiten blokkeren het bestand. Een historisch document is alleen-lezen en kan niet opnieuw worden verzonden, verwijderd, betaald gemarkeerd of omgezet. Nieuwe acties horen bij een nieuw document.
- Balans, resultatenrekening, auditfile, transacties, producten, periodieke facturen en andere rapporten blijven uitsluitend in het downloadbare bronarchief. Ze worden **niet** omgezet naar grootboekboekingen of actieve periodieke facturen. De bestandslijst in het controleoverzicht toont wat voor import is gebruikt.
- Duplicaten worden gekoppeld op eerder gekoppelde Moneybird-ID’s of dezelfde naam met compatibele e-mailgegevens. Gedeelde e-mailadressen bij verschillende bedrijfsnamen leiden niet tot samenvoegen. Ambigue contacten en documentnummers met afwijkende inhoud krijgen een conflict en worden overgeslagen. Bestaande klantvelden en documenten worden nooit overschreven. Het overzicht vermeldt de aantallen vóór bevestiging. Als de klant-/documentkoppelingen in de tussentijd wijzigen, is een nieuwe upload nodig. Herhaald bevestigen of dezelfde documenten opnieuw uploaden maakt geen dubbele documenten.

De extra bronvelden en contactpersonen zijn op de klantpagina te bekijken onder **Oorspronkelijke importgegevens en contactpersonen**. Geïmporteerde documenten verwijzen naar hun oorspronkelijke bronarchief. De app pakt geen archiefbestanden uit naar het bestandssysteem; onveilige paden, versleutelde bestanden, zipbommen, XML-entiteiten en te grote werkbladen worden geweigerd. Uploads zijn uitsluitend voor de ingelogde beheerder, vereisen CSRF en komen niet in Git of cookies. Maak vooraf een back-up van een bestaande administratie.

**Een bestaande Codespace bijwerken:** voer in de Terminal `git pull origin codespaces-setup` uit. Kies daarna in het opdrachtenpalet **Codespaces: Rebuild Container**. Dat installeert de nieuwe importafhankelijkheden en start de app opnieuw. De map `data/` in de checkout blijft bij deze rebuild behouden; verwijder de Codespace niet als je de testgegevens wilt bewaren. De database migreert automatisch van schema 1 of 2 naar 3.

## Veilig corrigeren
Uitgegeven documenten worden nooit gewijzigd of verwijderd. Een fout op een uitgegeven factuur moet buiten deze MVP worden gecorrigeerd met een afzonderlijke, rechtsgeldige creditnota die naar het oorspronkelijke factuurnummer verwijst. Bewaar die creditnota samen met de administratie en maak indien nodig een nieuwe factuur. Markeer een foutieve factuur niet betaald om deze te verbergen. De MVP maakt zelf geen creditnota's of boekhoudkundige verrekeningen. Vraag een boekhouder bij twijfel. Verwijdering van een klant met documenten is geblokkeerd; archiveren kan wel. Een logo is optioneel en upload wordt in deze versie niet aangeboden.

## SMTP
Sla server, poort (doorgaans 587), gebruiker, wachtwoord en afzender op. STARTTLS met certificaatcontrole is verplicht; implicit TLS op poort 465 wordt niet ondersteund. Testen controleert verbinding/authenticatie en verstuurt niets. De verzendactie voegt de PDF bij en markeert bij succes het document verzonden. Bij verbindingsfouten blijft de status behouden. Bij een onzekere netwerkfout kan de server het bericht al hebben ontvangen; controleer vóór opnieuw verzenden de mailbox. SMTP-wachtwoorden worden met Fernet versleuteld, afgeleid van MINIBIRD_SECRET, en nooit terug in HTML geplaatst. Bewaar deze sleutel veilig; wijzigen maakt bestaande SMTP-geheimen onleesbaar en beëindigt sessies. Het is toegestaan de SMTP-gegevens opnieuw in te voeren na een sleutelwissel. Geen echte e-mail in tests.

## Productie op Ubuntu 24.04
Installeer `python3-venv`, plaats de checkout bijvoorbeeld onder `/opt/minibird`, maak een onprivileged `minibird` gebruiker en een alleen voor die gebruiker toegankelijke map `/var/lib/minibird` (0700). Installeer de requirements in een venv. Maak `/etc/minibird.env` (0600) aan op basis van `.env.example`; genereer de geheime sleutel met `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. De app leest environment variables; `.env` wordt niet automatisch ingeladen.

Voorbeeld systemd-unit `/etc/systemd/system/minibird.service`:
```ini
[Unit]
Description=MiniBird
After=network.target
[Service]
User=minibird
Group=minibird
WorkingDirectory=/opt/minibird
EnvironmentFile=/etc/minibird.env
ExecStart=/opt/minibird/.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers --no-access-log
Restart=on-failure
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/minibird
[Install]
WantedBy=multi-user.target
```
Gebruik na lokale eerste setup een HTTPS reverse proxy (bijvoorbeeld Caddy met een eigen domein en geldig certificaat):
```caddy
facturen.example.nl {
    reverse_proxy 127.0.0.1:8000
}
```
`MINIBIRD_SECURE=true` is verplicht voor publiek gebruik. Expose poort 8000 niet; firewall alleen SSH en 80/443. Gebruik één worker, vertrouwde SMTP-instellingen, beperkte bestandstoegang en regelmatige OS-updates. Login wordt gelimiteerd tot vijf mislukte pogingen per 15 minuten per direct peeradres. Achter de proxy delen gebruikers één limiet; forwarded headers worden bewust niet vertrouwd. Dit is passend voor één beheerder, geen multi-tenant dienst. Sessies verlopen na 8 uur en zijn ondertekend, HttpOnly en SameSite=Lax. Lax staat een veilige terugkeer via de GitHub/Codespaces-authenticatie op een GET-pagina toe. Alle wijzigingen blijven door CSRF beschermd. Uploads gebruiken de CSRF-code uit het geopende formulier. Alleen na een geweigerde beveiligingscode wordt één keer een actuele code opgehaald uit de normale, ingelogde importpagina en wordt het verzoek opnieuw geprobeerd. Importbevestiging haalt eveneens een actuele code uit die pagina. De upload is niet afhankelijk van een aparte token-URL. Een geldige same-origin omleiding wordt geaccepteerd; een 403/404/503 wordt niet als verlopen sessie voorgesteld. Alleen een 401 of een echte omleiding naar de loginpagina vraagt opnieuw om inloggen. Bij een uploadfout blijft het gekozen bestand behouden. CSRF is verplicht bij alle wijzigingen inclusief login/logout/setup. Maak eerst een lokale beheerder voordat de reverse proxy publiek wordt. Er is geen wachtwoordreset via e-mail.

## Back-up, herstellen en bijwerken
```sh
.venv/bin/python -m app.backup data/minibird.sqlite /veilig/pad/minibird-backup.sqlite
```
SQLite online backup API maakt een consistente kopie en controleert `integrity_check`. Bestaande bestemmingen worden geweigerd. Bewaar ook MINIBIRD_SECRET afzonderlijk en beveilig back-ups als financiële gegevens. Test herstel regelmatig. Herstel: stop de service, bewaar de huidige database, controleer de backup met `sqlite3 backup.sqlite 'PRAGMA integrity_check'`, kopieer deze naar MINIBIRD_DB en herstel eigenaar/permissies 0600. Gebruik dezelfde sleutel en start de service; controleer login, klant en PDF. Herstel niet over een actieve database. Voor een update: maak een backup, stop de service, haal de nieuwe versie op, installeer requirements en start opnieuw. Schemawijzigingen worden bij starten gemigreerd; `PRAGMA user_version` bewaakt de versie. Huidige versie is 3; een database met een hogere versie wordt geweigerd. Rollback vereist bijpassende backup en codeversie.

## Validatie
```sh
.venv/bin/python -m pytest -q
.venv/bin/pip check
```
Tests voeren volledige HTTP-workflows uit via de echte ASGI-app en tijdelijke SQLite-databases: setup/login/logout, CSRF, loginlimiet, klanten, escaping/SQL-injectie, financiële afronding, offerteconversie, statussen, PDF, SMTP-mocks, migraties, backup en herstart. CI gebruikt dezelfde commando's. Browsercontrole is aanvullend; HTTP-tests bewijzen geen visuele correctheid.

Beveiligingskeuzes: Argon2id wachtwoorden, parameterized SQL, Jinja autoescaping, geen onbeveiligde HTML, CSP zonder inline scripts, vaste PDF-bestandsnamen, TLS-verificatie en versleutelde SMTP-geheimen. Applicatielogs bevatten uitsluitend event/methode/status, geen request bodies of klantgegevens. Zet uvicorn access logs uit in productie omdat URL's zoektermen kunnen bevatten. Geheimen en databases horen niet in Git. Een gecompromitteerde server met toegang tot sleutel en database kan SMTP-geheimen ontsleutelen. SQLite is bedoeld voor één bedrijf met beperkte gelijktijdigheid. Een verzendactie kan maximaal 15 seconden de databasewrite-lock vasthouden; geen bulkmail.

Licentiekeuze is nog niet vastgesteld door de eigenaar; zie LICENSE. De oude MiniBird-repository is niet gebruikt of gewijzigd.

Browser-smoketest (optioneel, aparte testafhankelijkheden; geen browser nodig op productie): installeer `pip install -r requirements-browser.txt`, installeer Chromium via het OS en voer `python tests/browser_smoke.py` uit in de venv. Gebruik `CHROMIUM_PATH` bij een afwijkend uitvoerbaar pad. De test start een eigen server en tijdelijke database, gebruikt uitsluitend fictieve gegevens en verwijdert deze na afloop. De test controleert ook meerdere factuurregels, PDF-download, mobiel dashboard en browserfouten. Screenshots worden tijdelijk onder `/tmp/minibird-desktop.png` en `/tmp/minibird-mobile.png` opgeslagen.
