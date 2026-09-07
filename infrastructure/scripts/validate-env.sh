#!/usr/bin/env bash
set -euo pipefail

required=(RICK_API_IMAGE RICK_WORKER_IMAGE RICK_WEB_IMAGE POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD RICK_EXTERNAL_DATABASE_DSN RICK_REDIS_URL RICK_QDRANT_URL RICK_OBJECT_STORE_ENDPOINT RICK_OBJECT_STORE_BUCKET)
missing=0
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    printf 'missing required deployment variable: %s\n' "$name" >&2
    missing=1
  fi
done
if (( missing )); then exit 2; fi
if [[ "${RICK_ENV:-}" != production ]]; then
  printf 'RICK_ENV must be production for this gate\n' >&2
  exit 2
fi
if [[ "${SESSION_COOKIE_SECURE:-}" != true ]]; then
  printf 'SESSION_COOKIE_SECURE must be true\n' >&2
  exit 2
fi
for name in POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD; do
  if [[ "${!name}" == REPLACE_* || "${!name}" == *example.invalid* ]]; then
    printf '%s is still a placeholder\n' "$name" >&2
    exit 2
  fi
done
printf 'deployment variable names and production safety flags: PASS\n'
