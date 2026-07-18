#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-phase5-i3-e2e}"
COMPOSE=(
  docker compose
  -p "$COMPOSE_PROJECT_NAME"
  -f "$ROOT_DIR/deploy/compose/compose.yaml"
  -f "$ROOT_DIR/deploy/compose/compose.e2e.yaml"
  --profile e2e
)

RESOURCE_EVENT_ID="evt-i3-resource-001"
RESOURCE_CENTER_ID="center-i3"
RESOURCE_ENTITY_ID="equipment-i3-001"
RESOURCE_CORRELATION_ID="corr-i3-resource-001"
PREVIEW_ID="00000000-0000-0000-0000-000000000301"
SNAPSHOT_ID="00000000-0000-0000-0000-000000000302"
WRITEBACK_OUTBOX_ID="00000000-0000-0000-0000-000000000303"
ORDER_ID="00000000-0000-0000-0000-000000000304"
PROJECT_ID="00000000-0000-0000-0000-000000000305"
STEP_ID="00000000-0000-0000-0000-000000000306"
EQUIPMENT_UUID="00000000-0000-0000-0000-000000000307"
PARTNER_RECORDER_URL="${PARTNER_RECORDER_URL:-http://127.0.0.1:18081}"
RABBIT_HTTP_URL="${RABBIT_HTTP_URL:-http://127.0.0.1:15672}"
RABBIT_HTTP_AUTH="${RABBIT_HTTP_AUTH:-guest:guest}"
POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-15432}"
RABBITMQ_AMQP_PORT="${RABBITMQ_AMQP_PORT:-5673}"
REDIS_HOST_PORT="${REDIS_HOST_PORT:-16379}"
I3_WORKER_MODE="${I3_WORKER_MODE:-docker}"
WORKER_PID=""
WORKER_LOG=""

cleanup() {
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" >/dev/null 2>&1; then
    kill "$WORKER_PID" >/dev/null 2>&1 || true
    wait "$WORKER_PID" >/dev/null 2>&1 || true
  fi
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

psql_value() {
  "${COMPOSE[@]}" exec -T postgres psql -U postgres -d detection_center -At -c "$1"
}

wait_for_match() {
  local description="$1"
  local sql="$2"
  local expected="$3"
  local attempts="${4:-60}"
  local sleep_seconds="${5:-1}"
  local actual

  for _ in $(seq 1 "$attempts"); do
    actual="$(psql_value "$sql" | tr -d '[:space:]')"
    if [[ "$actual" == "$expected" ]]; then
      return 0
    fi
    sleep "$sleep_seconds"
  done

  echo "Timed out waiting for ${description}. Expected ${expected}, got ${actual:-<empty>}." >&2
  return 1
}

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

retry_command() {
  local description="$1"
  local attempts="$2"
  shift 2
  local try

  for try in $(seq 1 "$attempts"); do
    if "$@"; then
      return 0
    fi
    if [[ "$try" -lt "$attempts" ]]; then
      echo "${description} failed on attempt ${try}/${attempts}; retrying..." >&2
      sleep 2
    fi
  done

  echo "${description} failed after ${attempts} attempts." >&2
  return 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Assertion failed: expected output to contain '$needle'" >&2
    echo "$haystack" >&2
    return 1
  fi
}

start_host_worker() {
  local build_dir
  build_dir="$(mktemp -d)"
  WORKER_LOG="${build_dir}/api-worker.log"
  (
    cd "${ROOT_DIR}/services/api-go"
    /usr/local/go/bin/go build -o "${build_dir}/api-worker" ./cmd/worker
  )
  APP_ENV=production \
  DATABASE_URL="postgres://postgres:postgres@127.0.0.1:${POSTGRES_HOST_PORT}/detection_center?sslmode=disable" \
  RABBITMQ_URL="amqp://guest:guest@127.0.0.1:${RABBITMQ_AMQP_PORT}/" \
  REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT}/0" \
  PARTNER_SCHEDULE_URL="${PARTNER_RECORDER_URL}" \
  "${build_dir}/api-worker" >"${WORKER_LOG}" 2>&1 &
  WORKER_PID="$!"
  for _ in $(seq 1 30); do
    if [[ -f "${WORKER_LOG}" ]] && grep -q "worker started" "${WORKER_LOG}"; then
      return 0
    fi
    if ! kill -0 "${WORKER_PID}" >/dev/null 2>&1; then
      cat "${WORKER_LOG}" >&2 || true
      echo "host api-worker exited unexpectedly" >&2
      return 1
    fi
    sleep 1
  done
  cat "${WORKER_LOG}" >&2 || true
  echo "Timed out waiting for host api-worker startup" >&2
  return 1
}

echo "Starting Phase 5 I3 stack..."
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d postgres rabbitmq redis partner-recorder
wait_http_ok "${PARTNER_RECORDER_URL}/healthz"

echo "Applying existing Goose SQL migrations..."
"${COMPOSE[@]}" run --rm migrate >/dev/null

echo "Starting real api-worker (${I3_WORKER_MODE})..."
if [[ "${I3_WORKER_MODE}" == "host" ]]; then
  start_host_worker
else
  retry_command "api-worker startup" 3 "${COMPOSE[@]}" up -d api-worker
fi

echo "Publishing a live RabbitMQ partner resource event..."
resource_publish="$(
  curl -fsS -u "$RABBIT_HTTP_AUTH" \
    -H 'content-type: application/json' \
    -d @- \
    "${RABBIT_HTTP_URL}/api/exchanges/%2F/partner.events/publish" <<JSON
{
  "properties": {
    "content_type": "application/json",
    "correlation_id": "${RESOURCE_CORRELATION_ID}",
    "delivery_mode": 2
  },
  "routing_key": "resource.equipment",
  "payload": "{\"event_id\":\"${RESOURCE_EVENT_ID}\",\"center_id\":\"${RESOURCE_CENTER_ID}\",\"event_type\":\"upserted\",\"entity_type\":\"equipment\",\"entity_id\":\"${RESOURCE_ENTITY_ID}\",\"source_version\":1,\"occurred_at\":\"2026-07-17T09:00:00Z\",\"payload\":{\"name\":\"E2E Chamber\",\"status\":\"ready\",\"capacity\":2}}",
  "payload_encoding": "string"
}
JSON
)"
assert_contains "$resource_publish" "\"routed\":true"

wait_for_match "processed inbox event" \
  "SELECT status FROM inbox_events WHERE event_id = '${RESOURCE_EVENT_ID}'" \
  "processed"
wait_for_match "equipment projection source version" \
  "SELECT source_version FROM equipment WHERE center_id = '${RESOURCE_CENTER_ID}' AND source_id = '${RESOURCE_ENTITY_ID}'" \
  "1"
wait_for_match "published rebuild outbox event" \
  "SELECT COUNT(*) FROM outbox_events WHERE event_type = 'schedule.rebuild.requested' AND published_at IS NOT NULL AND payload->>'center_id' = '${RESOURCE_CENTER_ID}'" \
  "1"

echo "Seeding an approved-pending-writeback preview..."
psql_value "
INSERT INTO schedule_snapshots (id, center_id, input_hash, as_of, base_schedule_version, resource_snapshot_version, payload, created_at)
VALUES ('${SNAPSHOT_ID}', '${RESOURCE_CENTER_ID}', 'hash-i3', '2026-07-17T10:00:00Z', 0, 1, '{}'::jsonb, now());
INSERT INTO schedule_previews (id, center_id, snapshot_id, status, candidate, normalized_steps, normalized_result_hash, version, created_at, updated_at)
VALUES ('${PREVIEW_ID}', '${RESOURCE_CENTER_ID}', '${SNAPSHOT_ID}', 'approved_pending_writeback', '{}'::jsonb, '[{\"id\":\"${STEP_ID}\",\"order_id\":\"${ORDER_ID}\",\"project_id\":\"${PROJECT_ID}\",\"equipment_id\":\"${EQUIPMENT_UUID}\",\"employee_ids\":[],\"starts_at\":\"2026-07-17T11:00:00Z\",\"ends_at\":\"2026-07-17T12:00:00Z\"}]'::jsonb, 'result-hash-i3', 3, now(), now());
INSERT INTO outbox_events (id, event_type, aggregate_type, aggregate_id, payload, occurred_at, created_at)
VALUES ('${WRITEBACK_OUTBOX_ID}', 'schedule.writeback', 'schedule_preview', '${PREVIEW_ID}', '{\"preview_id\":\"${PREVIEW_ID}\",\"center_id\":\"${RESOURCE_CENTER_ID}\"}'::jsonb, now(), now());
" >/dev/null

wait_for_match "approved preview" \
  "SELECT status FROM schedule_previews WHERE id = '${PREVIEW_ID}'" \
  "approved" \
  90
wait_for_match "formal schedule version" \
  "SELECT COUNT(*) FROM schedule_versions WHERE center_id = '${RESOURCE_CENTER_ID}' AND preview_id = '${PREVIEW_ID}' AND version = 1" \
  "1"
wait_for_match "expanded execution step" \
  "SELECT COUNT(*) FROM schedule_steps WHERE center_id = '${RESOURCE_CENTER_ID}' AND schedule_version = 1 AND id = '${STEP_ID}' AND status = 'scheduled'" \
  "1"
wait_for_match "published writeback outbox event" \
  "SELECT COUNT(*) FROM outbox_events WHERE id = '${WRITEBACK_OUTBOX_ID}' AND published_at IS NOT NULL" \
  "1"

echo "Checking recorded partner write-back request..."
partner_requests="$(curl -fsS "${PARTNER_RECORDER_URL}/requests")"
assert_contains "$partner_requests" "\"path\": \"/internal/v1/centers/${RESOURCE_CENTER_ID}/schedule-versions/1\""
assert_contains "$partner_requests" "\"if-match\": \"0\""
assert_contains "$partner_requests" "\"idempotency-key\""
assert_contains "$partner_requests" "\\\"preview_id\\\":\\\"${PREVIEW_ID}\\\""

echo "Phase 5 I3 live end-to-end checks passed."
