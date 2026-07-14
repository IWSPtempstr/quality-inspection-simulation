#!/usr/bin/env bash
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
CONDA_HOME="${CONDA_HOME:-$HOME/anaconda3}"
GO_HOME="${GO_HOME:-/usr/local/go}"

if [[ -s "$NVM_DIR/nvm.sh" ]]; then
  # shellcheck disable=SC1090
  . "$NVM_DIR/nvm.sh"
  nvm use 22.20.0 --silent
fi

export PATH="$GO_HOME/bin:$CONDA_HOME/bin:$PATH"
export npm_config_cache="${npm_config_cache:-$(pwd)/.npm-cache}"
export TMPDIR=/tmp
export TMP=/tmp
export TEMP=/tmp

for command in node npm go conda; do
  command -v "$command" >/dev/null || {
    echo "required tool is unavailable: $command" >&2
    exit 127
  }
done

[[ "$(node -v)" == v22.20.0 ]] || {
  echo "Node.js 22.20.0 is required; found $(node -v)" >&2
  exit 1
}

exec "$@"
