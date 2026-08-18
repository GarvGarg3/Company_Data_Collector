#!/usr/bin/env bash
#
# Run a project Python script from the host with the environment it expects.
#
#   scripts/run.sh build_site.py
#   scripts/run.sh normalize_countries.py --apply
#   scripts/run.sh scrapping/techstars.py --limit 50
#
# Inside Docker none of this is needed - compose injects the environment and
# installs the requirements. From the host, four things are missing, and this
# script supplies all of them:
#   1. a virtualenv with psycopg2 ("python" doesn't exist on macOS; system
#      python3 has no dependencies installed)
#   2. PYTHONPATH, so `from scripts import db_helper` resolves
#   3. the values in .env, which nothing loads into Python
#   4. PG_HOST=localhost - .env says "postgres", the compose service name,
#      which only resolves inside the compose network
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ $# -lt 1 ]; then
  echo "usage: scripts/run.sh <script.py> [args...]" >&2
  exit 2
fi

VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "No virtualenv found - creating .venv and installing requirements..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt"
  echo "Done." >&2
fi

REQUESTED="$1"; shift
# Accept either "build_site.py" or "scripts/build_site.py".
SCRIPT="$REQUESTED"
[ -f "$SCRIPT" ] || SCRIPT="scripts/$REQUESTED"
if [ ! -f "$SCRIPT" ]; then
  echo "No such script: $REQUESTED" >&2
  exit 2
fi

PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" exec "$VENV/bin/python" - "$SCRIPT" "$@" <<'PY'
import os, runpy, sys

# .env is written with "KEY = value" in places, which `source` can't parse -
# hence loading it here rather than in the shell. setdefault so a variable
# already exported on the command line still wins.
if os.path.exists(".env"):
    with open(".env", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

# The compose service name doesn't resolve from the host.
if os.environ.get("PG_HOST") == "postgres":
    os.environ["PG_HOST"] = "localhost"

script = sys.argv[1]
sys.argv = [script, *sys.argv[2:]]
runpy.run_path(script, run_name="__main__")
PY
