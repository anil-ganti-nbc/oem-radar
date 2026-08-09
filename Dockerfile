# OEM Radar — Linux AMD64 portability image. NOT approved for production
# (Tier C: portability + investigation only per current maturity policy).
FROM python:3.12-slim-bookworm

# Full Git SHA of the source this image was built from. Must be passed at
# build time (e.g. `--build-arg GIT_REVISION=$(git rev-parse HEAD)`, or via
# docker-compose.yml's build.args, which defaults to "unknown" for local/
# non-Git builds). Deliberately NOT derived from a .git directory at runtime
# -- no .git is copied into this image, and even if it were, the running
# container's filesystem is not proof of what was actually built.
ARG GIT_REVISION=unknown
LABEL clank.id="oem-radar" \
      org.opencontainers.image.revision="${GIT_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OEM_RADAR_OPEN_BROWSER=0 \
    OEM_RADAR_DATA_DIR=/app/data \
    OEM_RADAR_RELEASE_CHANNEL=experimental \
    OEM_RADAR_SOURCE_REVISION=${GIT_REVISION}

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin clank

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts

RUN pip install --upgrade pip \
    && pip install . \
    && mkdir -p /app/data/http_cache /app/data/raw \
    && chmod +x /app/scripts/*.sh \
    && chown -R clank:clank /app

USER clank

HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
    CMD ["oem-radar", "health"]

ENTRYPOINT ["/bin/sh", "/app/scripts/docker-entrypoint.sh"]
CMD ["run"]
