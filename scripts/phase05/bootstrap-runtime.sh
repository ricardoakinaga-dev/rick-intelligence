#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/.runtime"
UV_VERSION="0.8.14"
QDRANT_VERSION="1.7.4"
PYTHON_VERSION="3.12.3"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "Unsupported baseline architecture: $(uname -m) (expected x86_64)" >&2
  exit 2
fi

mkdir -p "$RUNTIME_DIR/bin" "$RUNTIME_DIR/downloads" "$RUNTIME_DIR/venvs"

if [[ ! -x "$RUNTIME_DIR/bin/uv" ]]; then
  curl -fsSL --retry 3 \
    -o "$RUNTIME_DIR/downloads/uv-${UV_VERSION}.tar.gz" \
    "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
  tar -xzf "$RUNTIME_DIR/downloads/uv-${UV_VERSION}.tar.gz" \
    -C "$RUNTIME_DIR/bin" --strip-components=1
fi

if [[ ! -x "$RUNTIME_DIR/venvs/cvg/bin/python" ]]; then
  "$RUNTIME_DIR/bin/uv" venv "$RUNTIME_DIR/venvs/cvg" --python /usr/bin/python3.12
fi

"$RUNTIME_DIR/bin/uv" pip install \
  --index-url https://pypi.org/simple \
  --python "$RUNTIME_DIR/venvs/cvg/bin/python" \
  -r "$REPO_ROOT/cvg-master-rag-v2/src/requirements.txt"

echo "Phase 0.5 runtime ready: Python ${PYTHON_VERSION}, uv ${UV_VERSION}, Qdrant ${QDRANT_VERSION} client/server target"
echo "Next: $REPO_ROOT/scripts/phase05/start-local-services.sh"
