#!/usr/bin/env bash
# Azure App Service startup command.
#
# Set this as the Startup Command under Configuration -> General settings:
#
#     startup.sh
#
# Without it Oryx guesses, and its guess for a Python app is a WSGI entry point
# it can find by name. FastAPI is ASGI, so it has to be told.
#
# Two workers, because B1 has one core and each worker holds its own model
# clients and its own slice of the database pool. Gunicorn supervises; uvicorn
# does the ASGI work.
set -e

exec gunicorn src.api.app:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 2 \
    --bind 0.0.0.0:"${PORT:-8000}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
