# Docker for uv Workspaces

Build from the workspace root so each member required by the application is available. Pin Python and uv images to reviewed releases, preferably digests. See the [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/) and [Docker build best practices](https://docs.docker.com/build/building/best-practices/).

```dockerfile
# Replace tags and digests through the repository's image-update process.
FROM python:3.14-slim@sha256:<reviewed-python-digest> AS builder
COPY --from=ghcr.io/astral-sh/uv:<reviewed-uv-release>@sha256:<reviewed-uv-digest> /uv /uvx /bin/
WORKDIR /app

# Metadata-only layer: source is deliberately absent.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY packages/core/pyproject.toml packages/core/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package my-api --no-install-workspace

COPY apps/api/ apps/api/
COPY packages/core/ packages/core/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package my-api

FROM python:3.14-slim@sha256:<reviewed-python-digest>
RUN useradd --no-log-init --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
CMD ["api"]
```

The final command is an installed console script, not a distribution-name-derived module. JSON-form `CMD` does not expand `${APP_NAME}`. If using `python -m`, supply a fixed valid import module such as `my_api.main`.

Use `--frozen` only in the metadata-only layer shown above. The final source-complete install uses `--locked` to verify the lock matches all project files. Avoid `PYTHONPATH` as a packaging workaround.

## Health checks and Compose

Use a standard-library check that fails on a non-2xx response:

```dockerfile
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"
```

Compose files are local-development configuration unless explicitly hardened. Do not embed production credentials. Use named volumes for stateful local services, health checks plus `depends_on` conditions where needed, and Compose secrets or environment injection for credentials. Omit the obsolete `version` key.

`.dockerignore` should exclude `.venv`, caches, local `.env`, and build output. Do not broadly exclude `*.md` when package metadata reads `README.md`, and retain `.git` when VCS versioning needs it.
