#!/usr/bin/env bash
# Wait for the in-flight FETCH to finish, then run the build chain.
# Same observer-proof process check as the chain: match a python process whose
# argv carries the script and `fetch` as a distinct token, never command-line
# text that a status query could also contain.
set -u
REPO="C:/Users/chris/clee/ARBS-snap"
PY="C:/Users/chris/anaconda3/envs/stir/python.exe"
cd "$REPO" || exit 1
export ARBS_SUPABASE_ENABLED=0

fetch_running() {
  "$PY" -c "
import os, sys, psutil
skip = {os.getpid(), $$}
for p in psutil.process_iter(['pid','name','cmdline']):
    try:
        if p.info['pid'] in skip: continue
        if (p.info['name'] or '').lower() not in ('python.exe','pythonw.exe'): continue
        cl = p.info['cmdline'] or []
        if any('deep_intraday_warm.py' in a for a in cl) and 'fetch' in cl:
            sys.exit(0)
    except Exception:
        continue
sys.exit(1)
"
}

echo "waiting for the fetch to finish  $(date '+%F %T')"
while fetch_running; do sleep 60; done
echo "fetch done; starting build chain  $(date '+%F %T')"
exec bash scripts/citivelo_build_until_done.sh
