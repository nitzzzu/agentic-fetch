#!/bin/bash
set -e
mkdir -p /data/chrome-profile

# Clean up stale X lock files from previous runs
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Clean up stale Chrome singleton locks from previous crashes
rm -f /data/chrome-profile/SingletonLock \
      /data/chrome-profile/SingletonCookie \
      /data/chrome-profile/SingletonSocket

# Virtual display — wait until actually ready
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
timeout=10
count=0
until xdpyinfo -display :99 > /dev/null 2>&1; do
    count=$((count+1))
    if [ $count -gt $timeout ]; then
        echo "ERROR: Xvfb failed to start"
        exit 1
    fi
    sleep 1
done
echo "Xvfb ready"

fluxbox 2>/dev/null &

# VNC server (raw port 5900)
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -quiet &

# noVNC web interface (port 6080)
/usr/share/novnc/utils/novnc_proxy --vnc localhost:5900 --listen 6080 &

# FastAPI service
exec uv run uvicorn agentic_fetch.main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1
