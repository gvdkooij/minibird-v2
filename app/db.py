import sqlite3
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), email TEXT NOT NULL, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL DEFAULT '{}');
INSERT OR IGNORE INTO settings(id) VALUES(1);
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, address TEXT NOT NULL, kvk TEXT NOT NULL, vat TEXT NOT NULL, contact TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, number TEXT UNIQUE NOT NULL, customer_id INTEGER NOT NULL REFERENCES customers(id), customer TEXT NOT NULL, company TEXT NOT NULL, lines TEXT NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft', date TEXT NOT NULL, due TEXT NOT NULL, source_id INTEGER UNIQUE REFERENCES documents(id));
CREATE TABLE IF NOT EXISTS counters(kind TEXT NOT NULL, year TEXT NOT NULL, value INTEGER NOT NULL, PRIMARY KEY(kind,year));
CREATE TABLE IF NOT EXISTS attempts(address TEXT NOT NULL, time REAL NOT NULL);

'''

def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def migrate(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > 3:
            raise RuntimeError('Database is nieuwer dan deze applicatie')
        # Run statements inside one transaction; executescript would commit early.
        for statement in SCHEMA.split(';'):
            if statement.strip(): db.execute(statement)
        if version < 2:
            db.execute("ALTER TABLE customers ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE customers ADD COLUMN import_extra TEXT NOT NULL DEFAULT '{}'")
            db.execute("CREATE TABLE import_batches(id TEXT PRIMARY KEY, created REAL NOT NULL, filename TEXT NOT NULL, payload TEXT NOT NULL, original BLOB NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '{}')")
            db.execute("CREATE TABLE import_links(source TEXT NOT NULL, external_id TEXT NOT NULL, customer_id INTEGER NOT NULL REFERENCES customers(id), PRIMARY KEY(source,external_id))")
            db.execute("CREATE TABLE document_imports(document_id INTEGER PRIMARY KEY REFERENCES documents(id), batch_id TEXT NOT NULL REFERENCES import_batches(id), fingerprint TEXT NOT NULL, original_status TEXT NOT NULL, pdf BLOB NOT NULL)")
        if version < 3:
            db.execute("CREATE TABLE import_uploads(id TEXT PRIMARY KEY, created REAL NOT NULL, filename TEXT NOT NULL, total_size INTEGER NOT NULL, received_size INTEGER NOT NULL DEFAULT 0, next_part INTEGER NOT NULL DEFAULT 0, batch_id TEXT REFERENCES import_batches(id))")
            db.execute("CREATE TABLE import_chunks(upload_id TEXT NOT NULL REFERENCES import_uploads(id) ON DELETE CASCADE, part INTEGER NOT NULL, digest TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(upload_id,part))")
        db.execute('PRAGMA user_version=3')


def backup(source, destination):
    if not Path(source).is_file():
        raise ValueError('Bronbestand bestaat niet')
    if Path(destination).exists():
        raise ValueError('Backup bestaat al')
    with connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Ongeldige backup')
