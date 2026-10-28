# MiniBird v2
Python 3.12+, FastAPI, SQLite, Jinja2, minimal vanilla JS. Use this existing isolated checkout; do not create worktrees unless requested.
Install: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
Validate: .venv/bin/python -m pytest -q; .venv/bin/pip check.
Start local: sh scripts/dev.sh. Never publicly expose development setup.
Use integer cents and Decimal half-up rounding per line. Keep issued documents and customer/company snapshots immutable. Number gaps are intentional; never reuse identifiers. Every mutating request must require a valid session CSRF token. Never send live SMTP messages from tests. Never log passwords, cookies, tokens or customer details. Back up SQLite and preserve MINIBIRD_SECRET before upgrades. Do not touch gvdkooij/minibird.
