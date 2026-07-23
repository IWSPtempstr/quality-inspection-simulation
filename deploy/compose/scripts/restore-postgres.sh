#!/bin/sh
set -eu

archive="${1:-}"
case "$archive" in
  ''|*/*)
    echo "usage: restore-postgres.sh <postgres-backup.dump>" >&2
    exit 1
    ;;
esac

source="/backups/$archive"
if [ ! -r "$source" ]; then
  echo "backup archive is unavailable: $archive" >&2
  exit 1
fi

if [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
  PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"
else
  PGPASSWORD="${POSTGRES_PASSWORD:-}"
fi
export PGPASSWORD

pg_restore --clean --if-exists --no-owner --no-privileges \
  -h "${POSTGRES_HOST:-postgres}" \
  -U "${POSTGRES_USER:?POSTGRES_USER is required}" \
  -d "${POSTGRES_DB:?POSTGRES_DB is required}" \
  "$source"
echo "restored ${archive}"
