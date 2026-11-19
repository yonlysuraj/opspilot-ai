FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/opspilot backend/opspilot
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --uid 10001 --create-home opspilot \
    && mkdir -p /var/lib/opspilot \
    && chown opspilot:opspilot /var/lib/opspilot
COPY --from=build /app/.venv /app/.venv
USER opspilot
CMD ["sh", "-c", "python -m opspilot.seed && exec python -m uvicorn opspilot.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
