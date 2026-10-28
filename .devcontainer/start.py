"""Start MiniBird on Codespaces attach/start; retain data in the checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def ready():
    try:
        with urlopen('http://127.0.0.1:8000/health', timeout=1) as response:
            return response.status == 200 and json.load(response) == {'status': 'ok'}
    except (URLError, TimeoutError, ValueError):
        return False


def start():
    if ready():
        print('MiniBird is al gestart. Open poort 8000 via het tabblad Ports.')
        return
    os.umask(0o077)
    data = ROOT / 'data'
    data.mkdir(exist_ok=True)
    with (data / 'codespaces.log').open('ab') as log:
        process = subprocess.Popen(
            ['sh', 'scripts/dev.sh'], cwd=ROOT,
            env={**os.environ, 'MINIBIRD_SECURE': 'true'},
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    for _ in range(60):
        if process.poll() is not None:
            raise SystemExit('MiniBird start niet. Bekijk data/codespaces.log.')
        if ready():
            print('MiniBird is gestart. Open de browserlink bij poort 8000 (Private) in Ports.')
            return
        time.sleep(0.5)
    process.terminate()
    raise SystemExit('Startcontrole verlopen. Bekijk data/codespaces.log.')


if __name__ == '__main__':
    start()
