#!/bin/bash
set -e

mkdir -p /data/chrome-profile

# Clean up stale X lock files from previous runs
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Clean up stale Chrome singleton locks from previous crashes
rm -f /data/chrome-profile/SingletonLock \
      /data/chrome-profile/SingletonCookie \
      /data/chrome-profile/SingletonSocket

exec supervisord -c /etc/supervisord.conf -n
