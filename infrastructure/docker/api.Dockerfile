# syntax=docker/dockerfile:1.7
#
# Build from the repository root. PYTHON_IMAGE is intentionally required and
# must be supplied as an immutable image reference with @sha256 digest.

ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/rick/apps/api/src:/opt/rick/apps/worker:/opt/rick/packages/jobs/src:/opt/rick/packages/contracts/src:/opt/rick/packages/authorization/src:/opt/rick/packages/identity/src:/opt/rick/packages/observability/src:/opt/rick/packages/knowledge/src:/opt/rick/packages/ingestion/src:/opt/rick/packages/retrieval/src:/opt/rick/packages/providers/src:/opt/rick/packages/locking/src:/opt/rick/packages/professor/src:/opt/rick/packages/evidence/src:/opt/rick/packages/decision/src:/opt/rick/packages/storage/src

WORKDIR /opt/rick

RUN addgroup --system --gid 10001 rick \
    && adduser --system --uid 10001 --ingroup rick --home /nonexistent \
       --shell /usr/sbin/nologin rick

COPY apps/api/pyproject.toml /opt/rick/apps/api/pyproject.toml
COPY apps/api/src /opt/rick/apps/api/src
COPY apps/worker /opt/rick/apps/worker
COPY infrastructure/migrations /opt/rick/infrastructure/migrations
COPY infrastructure/scripts/migrate.py /opt/rick/infrastructure/scripts/migrate.py
COPY infrastructure/compose/bootstrap_qdrant.py /opt/rick/infrastructure/compose/bootstrap_qdrant.py
COPY packages/jobs/src /opt/rick/packages/jobs/src
COPY packages/authorization/src /opt/rick/packages/authorization/src
COPY packages/contracts/src /opt/rick/packages/contracts/src
COPY packages/identity/src /opt/rick/packages/identity/src
COPY packages/ingestion/src /opt/rick/packages/ingestion/src
COPY packages/knowledge/src /opt/rick/packages/knowledge/src
COPY packages/locking/src /opt/rick/packages/locking/src
COPY packages/observability/src /opt/rick/packages/observability/src
COPY packages/professor/src /opt/rick/packages/professor/src
COPY packages/evidence/src /opt/rick/packages/evidence/src
COPY packages/decision/src /opt/rick/packages/decision/src
COPY packages/providers/src /opt/rick/packages/providers/src
COPY packages/retrieval/src /opt/rick/packages/retrieval/src
COPY packages/storage/src /opt/rick/packages/storage/src

# Direct dependencies are pinned to the canonical app/package contracts. The
# local packages stay on PYTHONPATH because the repository has no root wheel.
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      "fastapi==0.109.2" \
      "uvicorn==0.27.1" \
      "pydantic==2.6.1" \
      "python-multipart==0.0.9" \
      "httpx==0.27.0" \
      "anyio==4.15.0" \
      "PyJWT==2.7.0" \
      "pdfplumber==0.10.3" \
      "python-docx==1.1.0" \
      "psycopg[binary]==3.2.3" \
      "redis==5.2.1" \
      "opentelemetry-api==1.29.0" \
      "opentelemetry-sdk==1.29.0" \
      "opentelemetry-exporter-otlp-proto-grpc==1.29.0" \
    && python -m compileall -q /opt/rick/apps/api/src /opt/rick/apps/worker /opt/rick/packages \
    && find /opt/rick -type d -name __pycache__ -prune -exec rm -rf {} + \
    && chown -R 10001:10001 /opt/rick

USER 10001:10001

# Production must inject a deployment-owned module:factory that returns
# ExternalCompositionInputs; the empty default is intentionally fail-closed.
ENV RICK_API_COMPOSITION=""

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).read()" \
  || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "main:app", "--app-dir", "/opt/rick/apps/api/src", "--host", "0.0.0.0", "--port", "8000"]
