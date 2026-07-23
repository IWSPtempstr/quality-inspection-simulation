#!/bin/sh
set -eu

secret=/run/secrets/internal_service_token
if [ ! -r "$secret" ]; then
  echo "internal_service_token secret is unavailable" >&2
  exit 1
fi

export AI_SERVICE_SERVICE_BEARER_TOKEN="$(cat "$secret")"
exec "$@"
