#!/bin/sh
set -eu

password_file=/run/secrets/rabbitmq_default_password
if [ ! -r "$password_file" ]; then
  echo "rabbitmq_default_password secret is unavailable" >&2
  exit 1
fi

export RABBITMQ_DEFAULT_PASS="$(cat "$password_file")"
exec docker-entrypoint.sh rabbitmq-server
