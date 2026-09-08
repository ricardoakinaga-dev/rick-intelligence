# syntax=docker/dockerfile:1.7
#
# Build from the repository root. PYTHON_IMAGE is intentionally required and
# must be supplied as an immutable image reference with @sha256 digest.

ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/rick/apps/api/src:/opt/rick/apps/worker:/opt/rick/packages/contracts/src:/opt/rick/packages/authorization/src:/opt/rick/packages/identity/src:/opt/rick/packages/observability/src:/opt/rick/packages/knowledge/src:/opt/rick/packages/ingestion/src:/opt/rick/packages/retrieval/src:/opt/rick/packages/providers/src:/opt/rick/packages/locking/src:/opt/rick/packages/professor/src:/opt/rick/packages/storage/src

WORKDIR /opt/rick

RUN addgroup --system --gid 10001 rick \
    && adduser --system --uid 10001 --ingroup rick --home /nonexistent \
       --shell /usr/sbin/nologin rick

COPY apps/api/src /opt/rick/apps/api/src
COPY apps/worker /opt/rick/apps/worker
COPY packages/authorization/src /opt/rick/packages/authorization/src
COPY packages/contracts/src /opt/rick/packages/contracts/src
COPY packages/identity/src /opt/rick/packages/identity/src
COPY packages/ingestion/src /opt/rick/packages/ingestion/src
COPY packages/knowledge/src /opt/rick/packages/knowledge/src
COPY packages/locking/src /opt/rick/packages/locking/src
COPY packages/observability/src /opt/rick/packages/observability/src
COPY packages/professor/src /opt/rick/packages/professor/src
COPY packages/providers/src /opt/rick/packages/providers/src
COPY packages/retrieval/src /opt/rick/packages/retrieval/src
COPY packages/storage/src /opt/rick/packages/storage/src
COPY infrastructure/docker/worker-entrypoint.py /opt/rick/docker/worker-entrypoint.py

RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      "pydantic==2.6.1" \
      "httpx==0.27.0" \
      "anyio==4.15.0" \
      "PyJWT==2.7.0" \
    && python -m compileall -q /opt/rick/apps/api/src /opt/rick/apps/worker /opt/rick/packages /opt/rick/docker \
    && find /opt/rick -type d -name __pycache__ -prune -exec rm -rf {} + \
    && chown -R 10001:10001 /opt/rick

USER 10001:10001

# A deployment must inject a reviewed module:factory composition. Empty keeps
# the image fail-closed and does not embed any external client configuration.
ENV RICK_WORKER_COMPOSITION=""

# The worker is not an HTTP server. This healthcheck exercises the injected
# worker contract and fails closed when no production composition is present.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "/opt/rick/docker/worker-entrypoint.py", "--health-check"]

ENTRYPOINT ["python", "/opt/rick/docker/worker-entrypoint.py"]
