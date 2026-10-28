"""Usage: python -m app.backup DATABASE DESTINATION"""
import os
import sys
from .db import backup

if __name__=='__main__':
    os.umask(0o077)
    if len(sys.argv)!=3: raise SystemExit('Gebruik: python -m app.backup DATABASE DESTINATION')
    backup(*sys.argv[1:])
    print('Backup gemaakt en gecontroleerd. Bewaar ook de oorspronkelijke MINIBIRD_SECRET veilig.')
