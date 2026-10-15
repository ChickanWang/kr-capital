# Build context is the repo root (the app reads universe/ and seed/ from there).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# Supercronic (container-friendly cron) for the scheduler service.
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.49
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) sha=e63c11a9726b775a6a11801e81af4f3fb926aa68 ;; \
      arm64) sha=0b6c5bb743e0b0dafed1132198c81807927ac413 ;; \
      *) echo "unsupported arch ${TARGETARCH}"; exit 1 ;; \
    esac; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates; \
    curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH:-amd64}"; \
    echo "${sha}  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic; \
    apt-get purge -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/backend
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY universe/ /repo/universe/
COPY seed/ /repo/seed/
COPY docker/crontab /repo/docker/crontab

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
