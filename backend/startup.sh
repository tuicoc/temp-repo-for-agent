#!/bin/bash
# How App Service starts the backend. Its Startup Command is: bash startup.sh
#
# The five MCP servers run once each, over HTTP on the loopback interface,
# shared by every role (docs/design.md section 6.2), then the API. Over stdio
# every role would start its own five, and twenty processes of about 80 MB do
# not fit in a B1. Loopback only: a server trusts the role header it is sent.
# The ports are HTTP_URLS in src/mcp/client.py.
#
# A file rather than a line in the portal: the portal field kept the line
# breaks a terminal copy added to a 560-character command, and the container
# exited with 127 on 2026-09-27.

set -u
cd "$(dirname "$0")"

export MCP_TRANSPORT=http
# Voice weights and VieNeu's model go under /home, the only folder App Service
# keeps across restarts, so only a new instance downloads them.
export VOICE_MODELS_DIR="${VOICE_MODELS_DIR:-/home/models/voice}"
export HF_HOME="${HF_HOME:-/home/huggingface}"

python -m src.mcp.servers.memory --transport http --port 8801 &
python -m src.mcp.servers.catalog --transport http --port 8802 &
python -m src.mcp.servers.crm --transport http --port 8803 &
python -m src.mcp.servers.order --transport http --port 8804 &
python -m src.mcp.servers.knowledge --transport http --port 8805 &

# At once, without waiting for the servers: port 8000 must open early or the
# start time limit runs out. If they are still starting when the API warms
# up, it connects on the first turn instead.
exec python -m gunicorn src.api.app:app \
  --worker-class uvicorn.workers.UvicornWorker --workers 1 \
  --bind=0.0.0.0:8000 --timeout 120 \
  --access-logfile - --error-logfile -
