#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/.runtime"
QDRANT_VERSION="1.7.4"
QDRANT_HTTP_PORT="6337"
QDRANT_GRPC_PORT="6338"
REDIS_PORT="6380"

mkdir -p "$RUNTIME_DIR/bin" "$RUNTIME_DIR/downloads" "$RUNTIME_DIR/qdrant" "$RUNTIME_DIR/qdrant-storage" "$RUNTIME_DIR/redis"

if [[ ! -x "$RUNTIME_DIR/qdrant/qdrant" ]]; then
  curl -fsSL --retry 3 \
    -o "$RUNTIME_DIR/downloads/qdrant-${QDRANT_VERSION}.tar.gz" \
    "https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-gnu.tar.gz"
  tar -xzf "$RUNTIME_DIR/downloads/qdrant-${QDRANT_VERSION}.tar.gz" -C "$RUNTIME_DIR/qdrant"
fi

if ! curl -fsS --max-time 2 "http://127.0.0.1:${QDRANT_HTTP_PORT}/readyz" >/dev/null 2>&1; then
  (
    cd "$RUNTIME_DIR"
    QDRANT__SERVICE__HTTP_PORT="$QDRANT_HTTP_PORT" \
    QDRANT__SERVICE__GRPC_PORT="$QDRANT_GRPC_PORT" \
    QDRANT__STORAGE__STORAGE_PATH="$RUNTIME_DIR/qdrant-storage" \
      setsid "$RUNTIME_DIR/qdrant/qdrant" > "$RUNTIME_DIR/qdrant.log" 2>&1 < /dev/null &
    echo $! > "$RUNTIME_DIR/qdrant.pid"
  )
fi

if ! redis-cli -h 127.0.0.1 -p "$REDIS_PORT" ping >/dev/null 2>&1; then
  redis-server \
    --port "$REDIS_PORT" \
    --bind 127.0.0.1 \
    --dir "$RUNTIME_DIR/redis" \
    --dbfilename phase05.rdb \
    --save '' \
    --appendonly no \
    --daemonize yes \
    --pidfile "$RUNTIME_DIR/redis.pid" \
    --logfile "$RUNTIME_DIR/redis.log"
fi

for _ in {1..20}; do
  if curl -fsS --max-time 1 "http://127.0.0.1:${QDRANT_HTTP_PORT}/readyz" >/dev/null 2>&1 && \
     redis-cli -h 127.0.0.1 -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    echo "Qdrant ${QDRANT_VERSION}: http://127.0.0.1:${QDRANT_HTTP_PORT}"
    echo "Redis $(redis-server --version | awk '{print $3}') isolated port: ${REDIS_PORT}"
    exit 0
  fi
  sleep 1
done

echo "Local Phase 0.5 services did not become ready" >&2
exit 1
