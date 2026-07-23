#!/bin/sh
set -eu

if [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
  PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
else
  PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"
fi
export PGPASSWORD
host="${POSTGRES_HOST:-postgres}"
user="${POSTGRES_USER:-postgres}"
db="${POSTGRES_DB:-detection_center}"

until pg_isready -h "$host" -U "$user" -d "$db" >/dev/null 2>&1; do
  sleep 1
done

for file in /migrations/*.sql; do
  psql -v ON_ERROR_STOP=1 -h "$host" -U "$user" -d "$db" -f "$file"
done
