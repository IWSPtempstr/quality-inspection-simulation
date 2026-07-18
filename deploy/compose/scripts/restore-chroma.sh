#!/bin/sh
set -eu

archive="${1:-}"
if [ -z "$archive" ]; then
  echo "usage: restore-chroma.sh <archive-name.tgz>" >&2
  exit 1
fi

source="/backups/${archive}"
if [ ! -f "$source" ]; then
  echo "archive not found: ${source}" >&2
  exit 1
fi

rm -rf /data/*
tar -C /data -xzf "$source"
echo "restored ${source}"
