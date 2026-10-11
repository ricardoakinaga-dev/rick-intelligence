#!/usr/bin/env bash
set -euo pipefail
lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$lab_dir"
case "${1:-status}" in
  start) docker compose --env-file compose.env -f compose.json up -d ;;
  stop) docker compose --env-file compose.env -f compose.json stop ;;
  status) docker compose --env-file compose.env -f compose.json ps ;;
  logs) docker compose --env-file compose.env -f compose.json logs --tail 80 api worker web ;;
  *) printf 'Uso: %s {start|stop|status|logs}\n' "$0" >&2; exit 2 ;;
esac
