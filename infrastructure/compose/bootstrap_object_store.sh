#!/bin/sh
set -eu

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
: "${RICK_OBJECT_STORE_BUCKET:?RICK_OBJECT_STORE_BUCKET is required}"
: "${OBJECT_STORE_ACCESS_KEY_ID:?OBJECT_STORE_ACCESS_KEY_ID is required}"
: "${OBJECT_STORE_SECRET_ACCESS_KEY:?OBJECT_STORE_SECRET_ACCESS_KEY is required}"

export MC_CONFIG_DIR=/tmp/rick-mc
mkdir -p "$MC_CONFIG_DIR"
mc alias set local http://object-store:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing "local/$RICK_OBJECT_STORE_BUCKET" >/dev/null

policy_name="rick-${RICK_OBJECT_STORE_BUCKET}-app"
policy_file=/tmp/rick-object-policy.json
cat > "$policy_file" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {"Action": ["s3:GetBucketLocation", "s3:ListBucket"], "Effect": "Allow", "Resource": ["arn:aws:s3:::$RICK_OBJECT_STORE_BUCKET"]},
    {"Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], "Effect": "Allow", "Resource": ["arn:aws:s3:::$RICK_OBJECT_STORE_BUCKET/*"]}
  ]
}
EOF

if ! mc admin policy info local "$policy_name" >/dev/null 2>&1; then
  mc admin policy create local "$policy_name" "$policy_file" >/dev/null
fi
if ! mc admin user info local "$OBJECT_STORE_ACCESS_KEY_ID" >/dev/null 2>&1; then
  mc admin user add local "$OBJECT_STORE_ACCESS_KEY_ID" "$OBJECT_STORE_SECRET_ACCESS_KEY" >/dev/null
fi
mc admin policy attach local "$policy_name" --user "$OBJECT_STORE_ACCESS_KEY_ID" >/dev/null
rm -f "$policy_file"
