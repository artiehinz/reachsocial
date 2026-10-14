FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY templates ./templates
COPY static ./static
COPY examples ./examples
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --from=builder /app /app
RUN /usr/local/bin/python -m pip uninstall -y pip setuptools wheel \
    && useradd --create-home --uid 10001 appuser \
    && install -d -o appuser -g appuser -m 0700 /data
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "umask 077; chmod 700 /data; if [ -f /data/reachsocial.db ]; then chmod 600 /data/reachsocial.db; fi; alembic upgrade head && exec uvicorn reachsocial.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
