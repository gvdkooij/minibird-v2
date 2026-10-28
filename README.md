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
`MINIBIRD_SECURE=true` is verplicht voor publiek gebruik. Expose poort 8000 niet; firewall alleen SSH en 80/443. Gebruik één worker, vertrouwde SMTP-instellingen, beperkte bestandstoegang en regelmatige OS-updates. Login wordt gelimiteerd tot vijf mislukte pogingen per 15 minuten per direct peeradres. Achter de proxy delen gebruikers één limiet; forwarded headers worden bewust niet vertrouwd. Dit is passend voor één beheerder, geen multi-tenant dienst. Sessies verlopen na 8 uur en zijn ondertekend, HttpOnly en SameSite=Strict. CSRF is verplicht bij alle wijzigingen inclusief login/logout/setup. Maak eerst een lokale beheerder voordat de reverse proxy publiek wordt. Er is geen wachtwoordreset via e-mail.

## Back-up, herstellen en bijwerken
```sh
.venv/bin/python -m app.backup data/minibird.sqlite /veilig/pad/minibird-backup.sqlite
```
SQLite online backup API maakt een consistente kopie en controleert `integrity_check`. Bestaande bestemmingen worden geweigerd. Bewaar ook MINIBIRD_SECRET afzonderlijk en beveilig back-ups als financiële gegevens. Test herstel regelmatig. Herstel: stop de service, bewaar de huidige database, controleer de backup met `sqlite3 backup.sqlite 'PRAGMA integrity_check'`, kopieer deze naar MINIBIRD_DB en herstel eigenaar/permissies 0600. Gebruik dezelfde sleutel en start de service; controleer login, klant en PDF. Herstel niet over een actieve database. Voor een update: maak een backup, stop de service, haal de nieuwe versie op, installeer requirements en start opnieuw. Schemawijzigingen worden bij starten gemigreerd; `PRAGMA user_version` bewaakt de versie. Huidige versie is 1; een database met een hogere versie wordt geweigerd. Rollback vereist bijpassende backup en codeversie.

## Validatie
```sh
.venv/bin/python -m pytest -q
.venv/bin/pip check
```
Tests voeren volledige HTTP-workflows uit via de echte ASGI-app en tijdelijke SQLite-databases: setup/login/logout, CSRF, loginlimiet, klanten, escaping/SQL-injectie, financiële afronding, offerteconversie, statussen, PDF, SMTP-mocks, migraties, backup en herstart. CI gebruikt dezelfde commando's. Browsercontrole is aanvullend; HTTP-tests bewijzen geen visuele correctheid.

Beveiligingskeuzes: Argon2id wachtwoorden, parameterized SQL, Jinja autoescaping, geen onbeveiligde HTML, CSP zonder inline scripts, vaste PDF-bestandsnamen, TLS-verificatie en versleutelde SMTP-geheimen. Applicatielogs bevatten uitsluitend event/methode/status, geen request bodies of klantgegevens. Zet uvicorn access logs uit in productie omdat URL's zoektermen kunnen bevatten. Geheimen en databases horen niet in Git. Een gecompromitteerde server met toegang tot sleutel en database kan SMTP-geheimen ontsleutelen. SQLite is bedoeld voor één bedrijf met beperkte gelijktijdigheid. Een verzendactie kan maximaal 15 seconden de databasewrite-lock vasthouden; geen bulkmail.

Licentiekeuze is nog niet vastgesteld door de eigenaar; zie LICENSE. De oude MiniBird-repository is niet gebruikt of gewijzigd.

Browser-smoketest (optioneel, aparte testafhankelijkheden; geen browser nodig op productie): installeer `pip install -r requirements-browser.txt`, installeer Chromium via het OS en voer `python tests/browser_smoke.py` uit in de venv. Gebruik `CHROMIUM_PATH` bij een afwijkend uitvoerbaar pad. De test start een eigen server en tijdelijke database, gebruikt uitsluitend fictieve gegevens en verwijdert deze na afloop. De test controleert ook meerdere factuurregels, PDF-download, mobiel dashboard en browserfouten. Screenshots worden tijdelijk onder `/tmp/minibird-desktop.png` en `/tmp/minibird-mobile.png` opgeslagen.
