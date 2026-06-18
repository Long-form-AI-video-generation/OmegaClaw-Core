
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_SH="${RUN_SH:-$ROOT/../../run.sh}"
LOG_DIR="$ROOT/logs"

if [ ! -f "$RUN_SH" ]; then
    echo "ERROR: run.sh not found at $ROOT — place run.sh in the OmegaClaw-Core root directory."
    exit 1
fi

mkdir -p "$LOG_DIR"
mkdir -p "$ROOT/memory/history"
mkdir -p "$ROOT/memory/prompts"

SECRET="${OMEGACLAW_AUTH_SECRET:-}"
if [ -z "$SECRET" ]; then
    echo "WARNING: OMEGACLAW_AUTH_SECRET is not set. Proceeding without it."
fi

RUNSH_DIR="$(cd "$(dirname "$RUN_SH")" && pwd)"

run_agent() {
    local id=$1
    shift
    echo "Starting $id..."
    ( cd "$RUNSH_DIR" && \
      OMEGACLAW_AUTH_SECRET="$SECRET" OMEGACLAW_INSTANCE_ID="$id" \
      PYTHONDONTWRITEBYTECODE=1 \
      sh "$RUN_SH" run.metta "$@" \
      > "$LOG_DIR/$id.log" 2>&1 ) &
    echo "  $id started (PID $!) — logs: logs/$id.log"
}


echo "Starting web UI..."
cd "$ROOT" && python channels/web_ui.py > "$LOG_DIR/web_ui.log" 2>&1 &
echo "  web_ui started (PID $!) — logs: logs/web_ui.log"

( cd "$RUNSH_DIR" && \
  OMEGACLAW_AUTH_SECRET="$SECRET" OMEGACLAW_INSTANCE_ID="cosa" COMMCHANNEL=web \
  PYTHONDONTWRITEBYTECODE=1 \
  sh "$RUN_SH" run.metta instanceId=cosa commchannel=web wakeupInterval=60 \
  > "$LOG_DIR/cosa.log" 2>&1 ) &
echo "  cosa started (PID $!) — logs: logs/cosa.log"


run_agent cda \
    instanceId=cda \
    commchannel=none \
    wakeupInterval=300


run_agent swa \
    instanceId=swa \
    commchannel=none \
    wakeupInterval=300

# # PPA — Production Pipeline 
# run_agent ppa \
#     instanceId=ppa \
#     promptFile=./memory/prompts/ppa.txt \
#     historyFile=./memory/history/ppa.metta \
#     commchannel=none \
#     wakeupInterval=60

# # CRA — Client Relations 
# run_agent cra \
#     instanceId=cra \
#     promptFile=./memory/prompts/cra.txt \
#     historyFile=./memory/history/cra.metta \
#     commchannel=none \
#     wakeupInterval=600

# # DAA — Distribution & Analytics — wakes every hour
# run_agent daa \
#     instanceId=daa \
#     promptFile=./memory/prompts/daa.txt \
#     historyFile=./memory/history/daa.metta \
#     commchannel=none \
#     wakeupInterval=3600

echo ""
echo "All 6 agents started. Logs in logs/"
echo "CoSA web UI → http://localhost:8082"
echo ""
echo "To stop all agents:"
echo "  pkill -f 'swipl.*run.metta' && pkill -f 'web_ui.py'"
