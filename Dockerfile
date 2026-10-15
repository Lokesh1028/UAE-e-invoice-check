# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
# non-root user; data dir for the optional leads file
RUN useradd -r -u 10001 -d /srv app && mkdir -p /srv/data && chown -R app:app /srv
USER app
ENV PORT=8080 WEB_CONCURRENCY=2 DATA_DIR=/srv/data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:${PORT}/healthz || exit 1
# one uvicorn master with WEB_CONCURRENCY workers; each worker compiles the rule sets once at startup
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --timeout-keep-alive 15 --limit-concurrency 200 --backlog 512 --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
