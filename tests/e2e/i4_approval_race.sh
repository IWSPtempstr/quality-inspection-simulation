#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-phase5-i4-race}"
COMPOSE=(
  docker compose
  -p "$COMPOSE_PROJECT_NAME"
  -f "$ROOT_DIR/deploy/compose/compose.yaml"
  -f "$ROOT_DIR/deploy/compose/compose.e2e.yaml"
  --profile e2e
)

POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-15432}"
RABBITMQ_AMQP_PORT="${RABBITMQ_AMQP_PORT:-5673}"
REDIS_HOST_PORT="${REDIS_HOST_PORT:-16379}"
PARTNER_RECORDER_URL="${PARTNER_RECORDER_URL:-http://127.0.0.1:18081}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18080}"
OIDC_BASE_URL="${OIDC_BASE_URL:-http://127.0.0.1:18082}"
API_PID=""
OIDC_STUB_PID=""
TMP_DIR=""

cleanup() {
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" >/dev/null 2>&1; then
    kill "${API_PID}" >/dev/null 2>&1 || true
    wait "${API_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${OIDC_STUB_PID}" ]] && kill -0 "${OIDC_STUB_PID}" >/dev/null 2>&1; then
    kill "${OIDC_STUB_PID}" >/dev/null 2>&1 || true
    wait "${OIDC_STUB_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_http_ok() {
  local url="$1"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for HTTP endpoint: $url" >&2
  return 1
}

wait_service_healthy() {
  local service="$1"
  for _ in $(seq 1 60); do
    local status
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${COMPOSE_PROJECT_NAME}-${service}-1" 2>/dev/null || true)"
    if [[ "${status}" == "healthy" ]] || [[ "${status}" == "running" && "${service}" == "partner-recorder" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for service to become healthy: $service" >&2
  return 1
}

psql_value() {
  "${COMPOSE[@]}" exec -T postgres psql -U postgres -d detection_center -At -c "$1"
}

start_oidc_stub() {
  TMP_DIR="$(mktemp -d)"
  local port="${OIDC_BASE_URL##*:}"
  PORT="${port}" ISSUER_BASE_URL="${OIDC_BASE_URL}" \
    python3 "${ROOT_DIR}/tests/e2e/oidc-stub/server.py" >"${TMP_DIR}/oidc.log" 2>&1 &
  OIDC_STUB_PID="$!"
  wait_http_ok "${OIDC_BASE_URL}/realms/detection-center/.well-known/openid-configuration"
}

start_host_api() {
  (
    cd "${ROOT_DIR}/services/api-go"
    /usr/local/go/bin/go build -o "${TMP_DIR}/api-go" ./cmd/api
  )
  APP_ENV=production \
  HTTP_ADDR="127.0.0.1:18080" \
  DATABASE_URL="postgres://postgres:postgres@127.0.0.1:${POSTGRES_HOST_PORT}/detection_center?sslmode=disable" \
  RABBITMQ_URL="amqp://guest:guest@127.0.0.1:${RABBITMQ_AMQP_PORT}/" \
  REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT}/0" \
  INTERNAL_SERVICE_TOKEN="i4-internal-token" \
  OIDC_ISSUER_URL="${OIDC_BASE_URL}/realms/detection-center" \
  OIDC_CLIENT_ID="detection-center-web" \
  PARTNER_SCHEDULE_URL="${PARTNER_RECORDER_URL}/internal/v1/centers/health/schedule-versions/1" \
  NOTIFICATION_WEBHOOK_STUB_URL="${PARTNER_RECORDER_URL}/notification-webhook" \
  AI_SERVICE_URL="http://127.0.0.1:18084" \
  "${TMP_DIR}/api-go" >"${TMP_DIR}/api.log" 2>&1 &
  API_PID="$!"
  wait_http_ok "${API_BASE_URL}/readyz"
}

echo "Starting Phase 5 I4 approval-race stack..."
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d postgres rabbitmq redis partner-recorder
wait_service_healthy postgres
wait_service_healthy rabbitmq
wait_service_healthy redis
wait_service_healthy partner-recorder
"${COMPOSE[@]}" run --rm migrate >/dev/null

start_oidc_stub
start_host_api

echo "Seeding a pending_review preview..."
"${COMPOSE[@]}" exec -T postgres psql -U postgres -d detection_center >/dev/null <"${ROOT_DIR}/tests/e2e/sql/i4_seed_pending_review_preview.sql"

session_token="$(
  python3 "${ROOT_DIR}/tests/e2e/oidc-stub/mint_session.py" \
    --issuer-base-url "${OIDC_BASE_URL}" \
    --subject "user-i4-scheduler" \
    --center-id "center-i4" \
    --role scheduler
)"

cookie="__Host-public_session=${session_token}"
preview_id="00000000-0000-0000-0000-000000000402"

approve_once() {
  local output="$1"
  local key="$2"
  curl -sS \
    -X POST \
    -H "Cookie: ${cookie}" \
    -H "Idempotency-Key: ${key}" \
    -H 'If-Match: 1' \
    -o "${output}.body" \
    -w '%{http_code}' \
    "${API_BASE_URL}/api/v1/schedule-previews/${preview_id}/approve" >"${output}.status"
}

echo "Racing two approval requests..."
approve_once "${TMP_DIR}/approve-a" "i4-race-a" &
pid_a=$!
approve_once "${TMP_DIR}/approve-b" "i4-race-b" &
pid_b=$!
wait "$pid_a"
wait "$pid_b"

status_a="$(cat "${TMP_DIR}/approve-a.status")"
status_b="$(cat "${TMP_DIR}/approve-b.status")"
body_a="$(cat "${TMP_DIR}/approve-a.body")"
body_b="$(cat "${TMP_DIR}/approve-b.body")"

combined="${status_a} ${status_b}"
if [[ "${combined}" != *"200"* ]] || [[ "${combined}" != *"409"* ]]; then
  echo "Expected one 200 and one 409 from concurrent approvals, got ${status_a} and ${status_b}" >&2
  echo "${body_a}" >&2
  echo "${body_b}" >&2
  exit 1
fi

final_status="$(psql_value "SELECT status FROM schedule_previews WHERE id = '${preview_id}'")"
final_version="$(psql_value "SELECT version FROM schedule_previews WHERE id = '${preview_id}'")"
writeback_count="$(psql_value "SELECT COUNT(*) FROM outbox_events WHERE aggregate_id = '${preview_id}' AND event_type = 'schedule.writeback'")"

if [[ "${final_status}" != "approved_pending_writeback" ]]; then
  echo "Expected preview status approved_pending_writeback, got ${final_status}" >&2
  exit 1
fi
if [[ "${final_version}" != "2" ]]; then
  echo "Expected preview version 2, got ${final_version}" >&2
  exit 1
fi
if [[ "${writeback_count}" != "1" ]]; then
  echo "Expected exactly one schedule.writeback outbox row, got ${writeback_count}" >&2
  exit 1
fi

echo "Phase 5 I4 approval race checks passed."
