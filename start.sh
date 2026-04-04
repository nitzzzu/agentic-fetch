#!/bin/bash
set -e
mkdir -p /data/chrome-profile

# Virtual display
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 1
fluxbox &

# VNC server (raw port 5900)
x11vnc -display :99 -forever -nopw -rfbport 5900 -quiet &

# noVNC web interface (port 6080)
/usr/share/novnc/utils/novnc_proxy --vnc localhost:5900 --listen 6080 &

# FastAPI service
exec uv run uvicorn agentic_fetch.main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1
