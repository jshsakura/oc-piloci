# piLoci — Multi-stage Dockerfile (ARM64 / Raspberry Pi 5)

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./

RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache -e .

# ============================================
# Stage 2: Runtime
# ============================================
FROM python:3.11-slim-bookworm AS runtime

LABEL maintainer="jshsakura"
LABEL description="piLoci — self-hosted multi-user LLM memory service"

RUN groupadd --gid 1000 piloci \
    && useradd --uid 1000 --gid piloci --shell /bin/bash --create-home piloci

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* && apt-get clean

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/app/src

WORKDIR /app
COPY --chown=piloci:piloci pyproject.toml README.md LICENSE ./
COPY --chown=piloci:piloci src/ ./src/

RUN mkdir -p /data && chown piloci:piloci /data

# ============================================
# Stage 3: Dev (no static files, src mounted via volume)
# ============================================
FROM runtime AS dev
USER piloci

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8314
ENV HOST=0.0.0.0

EXPOSE 8314

ENTRYPOINT ["piloci", "serve"]

# ============================================
# Stage 4: Production (includes pre-built static)
# ============================================
FROM runtime AS production

# Web static files — pre-built by CI (web/out/ → src/piloci/static/)
# In local dev, run: pnpm build inside web/ then cp -r web/out/* src/piloci/static/
COPY --chown=piloci:piloci src/piloci/static/ ./src/piloci/static/

USER piloci

EXPOSE 8314

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8314/healthz || exit 1

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8314
ENV HOST=0.0.0.0

ENTRYPOINT ["piloci", "serve"]
