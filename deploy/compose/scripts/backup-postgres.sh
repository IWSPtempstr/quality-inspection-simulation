#!/bin/sh
set -eu

if [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
  PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
else
  PGPASSWORD="${POSTGRES_PASSWORD:-}"
fi
export PGPASSWORD

host="${POSTGRES_HOST:-postgres}"
user="${POSTGRES_USER:?POSTGRES_USER is required}"
db="${POSTGRES_DB:?POSTGRES_DB is required}"
timestamp="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
archive="/backups/postgres-${timestamp}.dump"

mkdir -p /backups
pg_dump --format=custom --no-owner --no-privileges -h "$host" -U "$user" -d "$db" -f "$archive"
echo "created ${archive}"
