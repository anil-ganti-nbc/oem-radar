# Reproducible builds

Use Python 3.12 and uv 0.11.32: `uv sync --locked --all-extras && uv build`. Regenerate `requirements.container.lock` only from the committed uv lock. Build the digest-pinned image with the full Git SHA as `GIT_REVISION`. CI records package artifacts, SBOM, locks, provenance, and image ID. Do not publish or promote.
