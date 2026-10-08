#!/bin/sh
set -eu

: "${RICK_OBJECT_STORE_BUCKET:?RICK_OBJECT_STORE_BUCKET is required}"
: "${OBJECT_STORE_ACCESS_KEY_ID:?OBJECT_STORE_ACCESS_KEY_ID is required}"
: "${OBJECT_STORE_SECRET_ACCESS_KEY:?OBJECT_STORE_SECRET_ACCESS_KEY is required}"

# This init container deliberately receives only the pre-provisioned scoped
# application credential. Root credentials stay on the MinIO server; creating
# users/policies here would require root and is therefore an explicit platform
# provisioning responsibility (especially in staging).
export MC_CONFIG_DIR=/tmp/rick-mc
mkdir -p "$MC_CONFIG_DIR"
mc alias set local http://object-store:9000 "$OBJECT_STORE_ACCESS_KEY_ID" "$OBJECT_STORE_SECRET_ACCESS_KEY" >/dev/null
mc mb --ignore-existing "local/$RICK_OBJECT_STORE_BUCKET" >/dev/null
