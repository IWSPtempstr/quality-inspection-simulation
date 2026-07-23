#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="${COMPOSE_ENV_FILE:-/etc/detection-center/compose.env}"

if [ ! -r "$env_file" ]; then
  echo "COMPOSE_ENV_FILE is not readable: $env_file" >&2
  exit 1
fi

set -a
. "$env_file"
set +a

: "${PUBLIC_HOSTNAME:?PUBLIC_HOSTNAME is required}"
: "${CERTS_DIR:?CERTS_DIR is required}"
: "${ACME_WEBROOT_DIR:?ACME_WEBROOT_DIR is required}"
: "${ACME_EMAIL:?ACME_EMAIL is required}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to create the brief bootstrap certificate" >&2
  exit 1
fi

mkdir -p "$CERTS_DIR/live/$PUBLIC_HOSTNAME" "$ACME_WEBROOT_DIR"
certificate_dir="$CERTS_DIR/live/$PUBLIC_HOSTNAME"
if [ ! -f "$certificate_dir/fullchain.pem" ] || [ ! -f "$certificate_dir/privkey.pem" ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "$certificate_dir/privkey.pem" \
    -out "$certificate_dir/fullchain.pem" \
    -subj "/CN=$PUBLIC_HOSTNAME" >/dev/null 2>&1
fi

docker compose --env-file "$env_file" -f "$root/compose.prod.yaml" up -d nginx
rm -rf "$certificate_dir"
docker compose --env-file "$env_file" -f "$root/compose.prod.yaml" --profile acme run --rm certbot \
  certonly --webroot --webroot-path /var/www/certbot --email "$ACME_EMAIL" \
  --agree-tos --no-eff-email -d "$PUBLIC_HOSTNAME"
docker compose --env-file "$env_file" -f "$root/compose.prod.yaml" exec -T nginx nginx -s reload
