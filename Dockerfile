FROM python:3.13-slim-bookworm

ARG USER_UID=1000
ARG USER_GID=1000
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium \
    DISPLAY=:99 \
    HOME=/data/home \
    XDG_STATE_HOME=/data/state

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium xvfb x11vnc novnc websockify ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$USER_GID" fantasy \
    && useradd --uid "$USER_UID" --gid "$USER_GID" --home-dir /data/home --no-create-home fantasy \
    && mkdir -p /data/home /data/state /data/.f1fantasy \
    && chown -R fantasy:fantasy /data

WORKDIR /opt/f1fantasy
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir '.[account]'

USER fantasy
WORKDIR /data
EXPOSE 6080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=60s --timeout=15s --start-period=15m --retries=3 \
    CMD ["python", "-m", "f1fantasy.container", "health"]
ENTRYPOINT ["python", "-m", "f1fantasy.container"]
CMD ["daemon", "run", "--season-plan", "--allow-penalties"]
