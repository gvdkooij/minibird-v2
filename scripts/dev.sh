#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
mkdir -p data
if [ ! -f data/dev-secret ]; then
  .venv/bin/python -c 'import secrets; from pathlib import Path; Path("data/dev-secret").write_text(secrets.token_urlsafe(48))'
fi
export MINIBIRD_SECRET="$(cat data/dev-secret)"
export MINIBIRD_SECURE=false
exec .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
