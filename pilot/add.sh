#!/usr/bin/env bash
# Add N more expedientes to the pilot run and process them in the background:
#   ./add.sh            # 20
#   ./add.sh 40
#   ./add.sh 0          # add none: finish an interrupted run
# Selection spreads them over the themes plus "otros", and within each over contract types,
# counting what the run already has. Services and secrets come from ~/.placsp_pilot.env
# (the export lines of the README's "Run on the server"); the run dir from PILOT_RUN_DIR.
set -euo pipefail
cd "$(dirname "$0")"
N=${1:-20}
[ -f ~/.placsp_pilot.env ] && . ~/.placsp_pilot.env
export PILOT_RUN_DIR=${PILOT_RUN_DIR:-$HOME/pilot_runs/themes}
: "${NLP_SERVICE_URL:?set it in ~/.placsp_pilot.env}" "${VECTORIZER_URL:?}" "${QDRANT_URL:?}" "${NEO4J_URL:?}"
if pgrep -f "placsp_pilot run" >/dev/null; then echo "a pilot run is already going: $(pgrep -f 'placsp_pilot run')"; exit 1; fi
docker exec ollama_high ollama ps 2>/dev/null | grep -q "100% GPU" || echo "warning: ollama_high is not on the GPU (docker restart ollama_high)"

mkdir -p "$PILOT_RUN_DIR"
echo "=== $(date '+%F %T') add $N ===" >> "$PILOT_RUN_DIR/run.log"
nohup .venv/bin/python -m placsp_pilot run --add "$N" >> "$PILOT_RUN_DIR/run.log" 2>&1 &
echo "pid $!; log: tail -f $PILOT_RUN_DIR/run.log"
