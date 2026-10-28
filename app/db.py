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
PRAGMA user_version=1;
'''

def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def migrate(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] > 1:
            raise RuntimeError('Database is nieuwer dan deze applicatie')
        db.executescript(SCHEMA)


def backup(source, destination):
    if not Path(source).is_file():
        raise ValueError('Bronbestand bestaat niet')
    if Path(destination).exists():
        raise ValueError('Backup bestaat al')
    with connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Ongeldige backup')
