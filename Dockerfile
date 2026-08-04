# OEM Radar — Stage 1 portable image (Linux AMD64)
# Preserves existing application behavior. No Fleet control plane.
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="oem-radar"
LABEL org.opencontainers.image.description="Portable OEM Radar pilot (Stage 1)"
LABEL clank.id="oem-radar"
LABEL clank.stage="1"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OEM_RADAR_OPEN_BROWSER=0 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: none required beyond slim image for this stack (requests, pydantic, pyyaml, sqlite stdlib)
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin clank

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts

# Install package (no dev deps in production image)
RUN pip install --upgrade pip \
    && pip install . \
    && chmod +x /app/scripts/*.sh

# Data and evidence live on volumes; create mount points
RUN mkdir -p /app/data/http_cache /app/data/raw /app/data/evidence \
    && chown -R clank:clank /app

USER clank

# Default command: one-shot crawl (same as historical Windows hourly task)
# Override with `oem-radar health` / `dashboard` etc. via compose or docker run.
ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
CMD ["run"]
