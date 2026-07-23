#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="${COMPOSE_ENV_FILE:-/etc/detection-center/compose.env}"

docker compose --env-file "$env_file" -f "$root/compose.prod.yaml" --profile acme run --rm certbot \
  renew --webroot --webroot-path /var/www/certbot
docker compose --env-file "$env_file" -f "$root/compose.prod.yaml" exec -T nginx nginx -s reload
