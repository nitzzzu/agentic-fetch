FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates dumb-init \
    xvfb x11vnc fluxbox curl \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
       http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git clone --depth 1 https://github.com/novnc/noVNC.git /usr/share/novnc \
    && git clone --depth 1 https://github.com/novnc/websockify /usr/share/websockify \
    && apt-get purge -y git && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY . .

ENV DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    AF_HEADLESS=false \
    AF_USER_DATA_DIR=/data/chrome-profile

EXPOSE 8000 5900 6080

VOLUME ["/data"]

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["./start.sh"]
