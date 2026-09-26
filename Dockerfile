FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /usr/local/bin/uv

WORKDIR /app

# ── Dependencies (cached layer — only reruns when the lock file changes) ─────
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# ── Source ───────────────────────────────────────────────────────────────────
COPY app/ ./app/
COPY content/ ./content/

RUN addgroup --system app && adduser --system --ingroup app app && chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=10000

EXPOSE 10000

# Render sets $PORT. The container is only reachable through Render's proxy, so trusting its forwarded
# headers from any peer is safe here.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
