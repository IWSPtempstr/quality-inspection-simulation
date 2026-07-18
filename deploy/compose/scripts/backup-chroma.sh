#!/bin/sh
set -eu

timestamp="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
archive="/backups/chroma-${timestamp}.tgz"

mkdir -p /backups
tar -C /data -czf "$archive" .
echo "created ${archive}"
