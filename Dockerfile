FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /usr/local/bin/uv

WORKDIR /app

# ── Dependencies (cached layer — only reruns when the lock file changes) ─────
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# ── Source ───────────────────────────────────────────────────────────────────
COPY app/ ./app/
COPY content/ ./content/
COPY prompts/ ./prompts/

RUN addgroup --system app && adduser --system --ingroup app app && chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=10000

EXPOSE 10000

# Render sets $PORT. --proxy-headers is for the scheme (X-Forwarded-Proto) only; the client address used for rate
# limiting is resolved in app/limits.py, because uvicorn's '*' trusts the client-controlled leftmost
# X-Forwarded-For entry. Access logs are off so visitor IPs are not logged.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-server-header --no-access-log"]
