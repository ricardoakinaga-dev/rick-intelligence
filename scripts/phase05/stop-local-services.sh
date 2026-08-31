#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/.runtime"

if [[ -s "$RUNTIME_DIR/qdrant.pid" ]]; then
  qdrant_pid="$(< "$RUNTIME_DIR/qdrant.pid")"
  if [[ "$qdrant_pid" =~ ^[0-9]+$ ]] && kill -0 "$qdrant_pid" 2>/dev/null; then
    kill "$qdrant_pid"
  fi
fi

if [[ -s "$RUNTIME_DIR/redis.pid" ]]; then
  redis_pid="$(< "$RUNTIME_DIR/redis.pid")"
  if [[ "$redis_pid" =~ ^[0-9]+$ ]] && kill -0 "$redis_pid" 2>/dev/null; then
    kill "$redis_pid"
  fi
fi

echo "Stopped only the Phase 0.5 PIDs recorded in $RUNTIME_DIR."
