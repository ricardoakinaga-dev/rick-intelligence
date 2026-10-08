#!/bin/sh
set -eu
# Scoped existing credential only; no root user/policy or anonymous ACL mutation.
mc alias set scoped "$RICK_OBJECT_STORE_ENDPOINT" "$RICK_OBJECT_STORE_ACCESS_KEY_ID" "$RICK_OBJECT_STORE_SECRET_ACCESS_KEY" >/dev/null 2>&1
mc mb --ignore-existing "scoped/$RICK_OBJECT_STORE_BUCKET" >/dev/null 2>&1
mc anonymous get "scoped/$RICK_OBJECT_STORE_BUCKET" > /tmp/bucket-access 2>/dev/null
grep -q 'private' /tmp/bucket-access
rm -f /tmp/bucket-access
