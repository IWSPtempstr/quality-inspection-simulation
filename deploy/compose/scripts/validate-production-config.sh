#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="${COMPOSE_ENV_FILE:-/etc/detection-center/compose.env}"
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT HUP INT TERM

if [ ! -r "$env_file" ]; then
  echo "COMPOSE_ENV_FILE is not readable: $env_file" >&2
  exit 1
fi

docker compose --env-file "$env_file" -f "$root/compose.prod.yaml" config >"$rendered"

if grep -En 'ops-stub|guest|change-me-before-production|NOTIFICATION_WEBHOOK_STUB_URL' "$rendered" >/dev/null; then
  echo "production render contains a forbidden development value" >&2
  exit 1
fi

published=$(awk '/^[[:space:]]+published:/{gsub(/"/, "", $2); print $2}' "$rendered")
for port in $published; do
  case "$port" in
    80|443) ;;
    *)
      echo "production render exposes forbidden host port: $port" >&2
      exit 1
      ;;
  esac
done

if [ "$(printf '%s\n' "$published" | sort -u | tr '\n' ' ')" != "443 80 " ]; then
  echo "production render must expose exactly ports 80 and 443" >&2
  exit 1
fi

echo "production Compose render passed topology checks"
