#!/bin/sh
set -eu

service_secret=/run/secrets/scheduler_service_bearer_token
callback_secret=/run/secrets/scheduler_callback_service_token
if [ ! -r "$service_secret" ] || [ ! -r "$callback_secret" ]; then
  echo "scheduler service secrets are unavailable" >&2
  exit 1
fi

export SCHEDULER_SERVICE_BEARER_TOKEN="$(cat "$service_secret")"
export SCHEDULER_CALLBACK_SERVICE_TOKEN="$(cat "$callback_secret")"
exec "$@"
