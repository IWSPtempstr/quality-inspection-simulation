#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-phase5-i4-e2e}"
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
OPS_STUB_URL="${OPS_STUB_URL:-http://127.0.0.1:18082}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18080}"
API_PID=""
API_LOG=""
OIDC_STUB_PID=""
OIDC_STUB_LOG=""
TMP_DIR=""
FAILURES=()
AUTH_TOKEN=""
PERF_METRICS=()

cleanup() {
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" >/dev/null 2>&1; then
    kill "${API_PID}" >/dev/null 2>&1 || true
    wait "${API_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${TMP_DIR}" ]] && [[ -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
  if [[ -n "${OIDC_STUB_PID}" ]] && kill -0 "${OIDC_STUB_PID}" >/dev/null 2>&1; then
    kill "${OIDC_STUB_PID}" >/dev/null 2>&1 || true
    wait "${OIDC_STUB_PID}" >/dev/null 2>&1 || true
  fi
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

compose_ops() {
  docker compose \
    -p "$COMPOSE_PROJECT_NAME" \
    -f "$ROOT_DIR/deploy/compose/compose.yaml" \
    -f "$ROOT_DIR/deploy/compose/compose.e2e.yaml" \
    --profile e2e \
    --profile ops \
    "$@"
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

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Assertion failed: expected output to contain '$needle'" >&2
    echo "$haystack" >&2
    return 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "Assertion failed: expected output not to contain '$needle'" >&2
    echo "$haystack" >&2
    return 1
  fi
}

now_ms() {
  python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

record_metric() {
  local name="$1"
  local started="$2"
  local finished="$3"
  PERF_METRICS+=("${name}=$((finished - started))ms")
}

sql_scalar() {
  local query="$1"
  docker exec "${COMPOSE_PROJECT_NAME}-postgres-1" \
    psql -U postgres -d detection_center -tA -c "$query" | tr -d '[:space:]'
}

mint_scheduler_session() {
  AUTH_TOKEN="$(python3 "${ROOT_DIR}/tests/e2e/oidc-stub/mint_session.py" \
    --issuer-base-url "${OPS_STUB_URL}" \
    --subject "scheduler-e2e" \
    --center-id "center-e2e" \
    --role scheduler \
    --role admin \
    --name "I4 Scheduler")"
}

auth_json() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  shift 3 || true
  if [[ -n "${body}" ]]; then
    curl -fsS -X "${method}" \
      --cookie "__Host-public_session=${AUTH_TOKEN}" \
      -H "Content-Type: application/json" \
      "$@" \
      "${API_BASE_URL}${path}" \
      --data "${body}"
    return
  fi
  curl -fsS -X "${method}" \
    --cookie "__Host-public_session=${AUTH_TOKEN}" \
    "$@" \
    "${API_BASE_URL}${path}"
}

json_field() {
  local payload="$1"
  local field="$2"
  python3 -c 'import json, sys
data = json.loads(sys.argv[1])
value = data[sys.argv[2]]
if isinstance(value, (dict, list)):
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=False))
else:
    print(value)' "$payload" "$field"
}

candidate_hash() {
  local raw_json="$1"
  python3 -c 'import datetime as dt, hashlib, json, re, sys
timestamp = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
def normalize_string(value: str) -> str:
    if not timestamp.match(value):
        return value
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
def canonical(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(normalize_string(value), ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, "g")
    if isinstance(value, list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + canonical(value[key]) for key in sorted(value)) + "}"
    raise TypeError(f"unsupported canonical JSON value {type(value)!r}")
payload = json.loads(sys.argv[1])
print("sha256:" + hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest())' "$raw_json"
}

wait_for_health() {
  local expected_status="$1"
  local expected_component="$2"
  local expected_component_status="$3"
  local description="${4:-health state}"
  local response=""
  for _ in $(seq 1 60); do
    response="$(curl -fsS "${API_BASE_URL}/api/v1/system/health")"
    if [[ "$response" == *"\"status\":\"${expected_status}\""* ]] &&
      [[ "$response" == *"\"${expected_component}\":\"${expected_component_status}\""* ]]; then
      echo "$response"
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${description}. Last response: ${response:-<empty>}" >&2
  return 1
}

start_host_api() {
  TMP_DIR="$(mktemp -d)"
  API_LOG="${TMP_DIR}/api-go.log"
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
  OIDC_ISSUER_URL="${OPS_STUB_URL}/realms/detection-center" \
  OIDC_CLIENT_ID="detection-center-web" \
  PARTNER_SCHEDULE_URL="${PARTNER_RECORDER_URL}/internal/v1/centers/health/schedule-versions/1" \
  NOTIFICATION_WEBHOOK_STUB_URL="${PARTNER_RECORDER_URL}/notification-webhook" \
  AI_SERVICE_URL="http://127.0.0.1:18084" \
  "${TMP_DIR}/api-go" >"${API_LOG}" 2>&1 &
  API_PID="$!"
  for _ in $(seq 1 60); do
    if curl -fsS "${API_BASE_URL}/readyz" >/dev/null 2>/dev/null; then
      return 0
    fi
    if ! kill -0 "${API_PID}" >/dev/null 2>&1; then
      cat "${API_LOG}" >&2 || true
      echo "host api-go exited unexpectedly" >&2
      return 1
    fi
    sleep 1
  done
  cat "${API_LOG}" >&2 || true
  echo "Timed out waiting for HTTP endpoint: ${API_BASE_URL}/readyz" >&2
  return 1
}

restart_host_api() {
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" >/dev/null 2>&1; then
    kill "${API_PID}" >/dev/null 2>&1 || true
    wait "${API_PID}" >/dev/null 2>&1 || true
  fi
  API_PID=""
  start_host_api
}

start_oidc_stub() {
  TMP_DIR="$(mktemp -d)"
  OIDC_STUB_LOG="${TMP_DIR}/oidc-stub.log"
  PORT="${OPS_STUB_URL##*:}"
  ISSUER_BASE_URL="${OPS_STUB_URL}" \
  PORT="${PORT}" \
  python3 "${ROOT_DIR}/tests/e2e/oidc-stub/server.py" >"${OIDC_STUB_LOG}" 2>&1 &
  OIDC_STUB_PID="$!"
  wait_http_ok "${OPS_STUB_URL}/realms/detection-center/.well-known/openid-configuration"
  mint_scheduler_session
}

run_concurrent_approve_race() {
  local preview_id="$1"
  local version="$2"
  local body_one="${TMP_DIR}/approve-1.body"
  local body_two="${TMP_DIR}/approve-2.body"
  local status_one_file="${TMP_DIR}/approve-1.status"
  local status_two_file="${TMP_DIR}/approve-2.status"
  local started finished status_one status_two success_count outbox_count replay_status replay_body

  started="$(now_ms)"
  (
    curl -sS -o "${body_one}" -w '%{http_code}' \
      -X POST \
      --cookie "__Host-public_session=${AUTH_TOKEN}" \
      -H "Idempotency-Key: approve-race-1" \
      -H "If-Match: ${version}" \
      "${API_BASE_URL}/api/v1/schedule-previews/${preview_id}/approve" >"${status_one_file}"
  ) &
  local pid_one=$!
  (
    curl -sS -o "${body_two}" -w '%{http_code}' \
      -X POST \
      --cookie "__Host-public_session=${AUTH_TOKEN}" \
      -H "Idempotency-Key: approve-race-2" \
      -H "If-Match: ${version}" \
      "${API_BASE_URL}/api/v1/schedule-previews/${preview_id}/approve" >"${status_two_file}"
  ) &
  local pid_two=$!
  wait "${pid_one}"
  wait "${pid_two}"
  finished="$(now_ms)"
  record_metric "approve_race" "${started}" "${finished}"

  status_one="$(cat "${status_one_file}")"
  status_two="$(cat "${status_two_file}")"
  success_count=0
  [[ "${status_one}" == "200" ]] && success_count=$((success_count + 1))
  [[ "${status_two}" == "200" ]] && success_count=$((success_count + 1))
  if [[ "${success_count}" -ne 1 ]]; then
    echo "Expected exactly one concurrent approval success, got statuses ${status_one} and ${status_two}" >&2
    exit 1
  fi
  if [[ "${status_one}" != "409" && "${status_two}" != "409" ]]; then
    echo "Expected one concurrent approval conflict, got statuses ${status_one} and ${status_two}" >&2
    exit 1
  fi

  outbox_count="$(sql_scalar "SELECT COUNT(*) FROM outbox_events WHERE aggregate_id = '${preview_id}' AND event_type = 'schedule.writeback';")"
  if [[ "${outbox_count}" != "1" ]]; then
    echo "Expected one schedule.writeback outbox event after approval race, got ${outbox_count}" >&2
    exit 1
  fi

  replay_status="$(curl -sS -o "${TMP_DIR}/approve-replay.body" -w '%{http_code}' \
    -X POST \
    --cookie "__Host-public_session=${AUTH_TOKEN}" \
    -H "Idempotency-Key: approve-race-1" \
    -H "If-Match: ${version}" \
    "${API_BASE_URL}/api/v1/schedule-previews/${preview_id}/approve")"
  replay_body="$(cat "${TMP_DIR}/approve-replay.body")"
  if [[ "${status_one}" == "200" ]]; then
    if [[ "${replay_status}" != "200" ]] || [[ "${replay_body}" != "$(cat "${body_one}")" ]]; then
      echo "Expected winner approval replay to return the first successful response" >&2
      exit 1
    fi
  else
    if [[ "${replay_status}" != "409" ]]; then
      echo "Expected losing approval replay to remain conflicted, got ${replay_status}" >&2
      exit 1
    fi
  fi
}

seed_execution_race_fixture() {
  docker exec -i "${COMPOSE_PROJECT_NAME}-postgres-1" \
    psql -v ON_ERROR_STOP=1 -U postgres -d detection_center <<'SQL' >/dev/null
INSERT INTO orders (
  id, center_id, sample_name, sample_quantity, certification_type, priority,
  promised_finish_time, status, version, created_by, updated_by, created_at, updated_at
) VALUES (
  '11111111-1111-1111-1111-111111111111', 'center-e2e', 'I4 sample', 1, 'CCC', 'normal',
  '2026-07-17T12:00:00Z', 'scheduled', 1, 'scheduler-e2e', 'scheduler-e2e', now(), now()
);
INSERT INTO center_scheduler_users(center_id, user_id) VALUES
  ('center-e2e', 'scheduler-e2e'),
  ('center-e2e', 'scheduler-peer');
INSERT INTO schedule_steps (
  id, center_id, schedule_version, order_id, project_id, employee_ids,
  starts_at, ends_at, status, version, created_at, updated_at
) VALUES (
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'center-e2e', 1,
  '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222',
  '[]'::jsonb, '2026-07-17T08:00:00Z', '2026-07-17T09:00:00Z', 'scheduled', 1, now(), now()
);
SQL
  local seeded_steps
  seeded_steps="$(sql_scalar "SELECT COUNT(*) FROM schedule_steps WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' AND center_id = 'center-e2e';")"
  if [[ "${seeded_steps}" != "1" ]]; then
    echo "Expected the execution-race fixture to seed one schedule step, got ${seeded_steps}" >&2
    exit 1
  fi
}

run_concurrent_step_start_race() {
  local step_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
  local body_one="${TMP_DIR}/step-1.body"
  local body_two="${TMP_DIR}/step-2.body"
  local status_one_file="${TMP_DIR}/step-1.status"
  local status_two_file="${TMP_DIR}/step-2.status"
  local started finished status_one status_two success_count started_count notifications deliveries

  started="$(now_ms)"
  (
    curl -sS -o "${body_one}" -w '%{http_code}' \
      -X PATCH \
      --cookie "__Host-public_session=${AUTH_TOKEN}" \
      -H "Idempotency-Key: step-race-1" \
      -H "If-Match: 1" \
      "${API_BASE_URL}/api/v1/schedule-steps/${step_id}/start" >"${status_one_file}"
  ) &
  local pid_one=$!
  (
    curl -sS -o "${body_two}" -w '%{http_code}' \
      -X PATCH \
      --cookie "__Host-public_session=${AUTH_TOKEN}" \
      -H "Idempotency-Key: step-race-2" \
      -H "If-Match: 1" \
      "${API_BASE_URL}/api/v1/schedule-steps/${step_id}/start" >"${status_two_file}"
  ) &
  local pid_two=$!
  wait "${pid_one}"
  wait "${pid_two}"
  finished="$(now_ms)"
  record_metric "step_start_race" "${started}" "${finished}"

  status_one="$(cat "${status_one_file}")"
  status_two="$(cat "${status_two_file}")"
  success_count=0
  [[ "${status_one}" == "200" ]] && success_count=$((success_count + 1))
  [[ "${status_two}" == "200" ]] && success_count=$((success_count + 1))
  if [[ "${success_count}" -ne 1 ]]; then
    echo "Expected exactly one concurrent step-start success, got statuses ${status_one} and ${status_two}" >&2
    exit 1
  fi
  if [[ "${status_one}" != "409" && "${status_two}" != "409" ]]; then
    echo "Expected one concurrent step-start conflict, got statuses ${status_one} and ${status_two}" >&2
    exit 1
  fi

  started_count="$(sql_scalar "SELECT COUNT(*) FROM schedule_steps WHERE id = '${step_id}' AND status = 'running' AND version = 2;")"
  notifications="$(sql_scalar "SELECT COUNT(*) FROM notifications WHERE center_id = 'center-e2e' AND order_id = '11111111-1111-1111-1111-111111111111';")"
  deliveries="$(sql_scalar "SELECT COUNT(*) FROM notification_deliveries;")"
  if [[ "${started_count}" != "1" ]]; then
    echo "Expected one running schedule step row after the race, got ${started_count}" >&2
    exit 1
  fi
  if [[ "${notifications}" != "2" ]]; then
    echo "Expected two deduplicated notifications (creator + peer scheduler), got ${notifications}" >&2
    exit 1
  fi
  if [[ "${deliveries}" != "2" ]]; then
    echo "Expected two notification delivery rows after the step-start race, got ${deliveries}" >&2
    exit 1
  fi
}

echo "Starting Phase 5 I4 dependency stack..."
"${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d postgres rabbitmq redis partner-recorder
wait_http_ok "${PARTNER_RECORDER_URL}/healthz"
start_oidc_stub

echo "Applying existing Goose SQL migrations..."
"${COMPOSE[@]}" run --rm migrate >/dev/null

echo "Verifying Chroma backup and restore..."
"${COMPOSE[@]}" run --rm chroma-volume-helper "mkdir -p /data/i4 && printf 'phase5-i4-original' > /data/i4/sentinel.txt"
backup_output="$(compose_ops run --rm chroma-backup i4-restore-smoke)"
assert_contains "$backup_output" "created /backups/chroma-i4-restore-smoke.tgz"
"${COMPOSE[@]}" run --rm chroma-volume-helper "printf 'phase5-i4-mutated' > /data/i4/sentinel.txt"
compose_ops run --rm chroma-restore chroma-i4-restore-smoke.tgz >/dev/null
restored_sentinel="$("${COMPOSE[@]}" run --rm chroma-volume-helper "cat /data/i4/sentinel.txt")"
if [[ "${restored_sentinel}" != "phase5-i4-original" ]]; then
  echo "Expected restored sentinel to match original backup content, got '${restored_sentinel}'" >&2
  exit 1
fi

echo "Starting host api-go for health and outage drills..."
start_host_api

health_started_ms="$(now_ms)"
baseline_health="$(wait_for_health healthy postgres available "baseline healthy state")"
health_finished_ms="$(now_ms)"
record_metric "health_baseline" "${health_started_ms}" "${health_finished_ms}"
assert_contains "$baseline_health" "\"rabbitmq\":\"available\""
assert_contains "$baseline_health" "\"redis\":\"available\""
assert_contains "$baseline_health" "\"partner_writeback\":\"available\""
assert_contains "$baseline_health" "\"notification_channel\":\"available\""
assert_not_contains "$baseline_health" "http://"
assert_not_contains "$baseline_health" "127.0.0.1"
assert_not_contains "$baseline_health" "trace"
assert_not_contains "$baseline_health" "panic"

session_status="$(curl -sS -o /dev/null -w '%{http_code}' "${API_BASE_URL}/api/v1/session/me")"
if [[ "${session_status}" != "401" ]]; then
  echo "Expected unauthenticated /api/v1/session/me to return 401, got ${session_status}" >&2
  exit 1
fi

echo "Checking authenticated preview approval race and idempotent replay..."
preview_started_ms="$(now_ms)"
preview_create_response="$(auth_json POST "/api/v1/schedule-previews" "" -H "Idempotency-Key: i4-preview-create")"
preview_finished_ms="$(now_ms)"
record_metric "preview_create" "${preview_started_ms}" "${preview_finished_ms}"
preview_id="$(json_field "${preview_create_response}" id)"
snapshot_id="$(json_field "${preview_create_response}" snapshot_id)"
preview_version="$(json_field "${preview_create_response}" version)"
candidate_payload='{"input_hash":"placeholder","algorithm_used":"cp_sat","solver_status":"optimal","fallback_used":false,"fallback_reason":null,"blocked_steps":[],"schedule":{"steps":[{"id":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","order_id":"11111111-1111-1111-1111-111111111111","project_id":"22222222-2222-2222-2222-222222222222","starts_at":"2026-07-17T08:00:00Z","ends_at":"2026-07-17T09:00:00Z"}]},"metrics":{"scheduled_step_count":1}}'
snapshot_hash="$(sql_scalar "SELECT input_hash FROM schedule_snapshots WHERE id = '${snapshot_id}';")"
candidate_payload="${candidate_payload/\"placeholder\"/\"${snapshot_hash}\"}"
candidate_result_hash="$(candidate_hash "${candidate_payload}")"
callback_body="$(python3 -c 'import json, sys
snapshot_id, input_hash, version, result_hash, candidate = sys.argv[1:]
print(json.dumps({
    "snapshot_id": snapshot_id,
    "input_hash": input_hash,
    "version": int(version),
    "normalized_result_hash": result_hash,
    "candidate": json.loads(candidate),
}, separators=(",", ":"), ensure_ascii=False))' "$snapshot_id" "$snapshot_hash" "$preview_version" "$candidate_result_hash" "$candidate_payload")"
callback_started_ms="$(now_ms)"
callback_response="$(curl -fsS \
  -X POST \
  -H "X-Scheduler-Callback-Token: i4-internal-token" \
  -H "Content-Type: application/json" \
  --data "${callback_body}" \
  "${API_BASE_URL}/internal/v1/schedule-previews/${preview_id}/candidate")"
callback_finished_ms="$(now_ms)"
record_metric "candidate_callback" "${callback_started_ms}" "${callback_finished_ms}"
callback_version="$(json_field "${callback_response}" version)"
run_concurrent_approve_race "${preview_id}" "${callback_version}"

echo "Checking authenticated execution race and recipient de-duplication..."
seed_execution_race_fixture
run_concurrent_step_start_race

echo "Checking degraded health when RabbitMQ is unavailable..."
"${COMPOSE[@]}" stop rabbitmq >/dev/null
rabbitmq_health="$(wait_for_health degraded rabbitmq degraded "rabbitmq degraded state")"
assert_contains "$rabbitmq_health" "\"status\":\"degraded\""
"${COMPOSE[@]}" up -d rabbitmq >/dev/null
wait_service_healthy rabbitmq
if ! wait_for_health healthy rabbitmq available "rabbitmq recovery" >/dev/null; then
  FAILURES+=("rabbitmq outage requires api-go restart before health returns to healthy")
  restart_host_api
  wait_for_health healthy rabbitmq available "rabbitmq recovery after api-go restart" >/dev/null
fi

echo "Checking degraded health when Redis is unavailable..."
"${COMPOSE[@]}" stop redis >/dev/null
redis_health="$(wait_for_health degraded redis degraded "redis degraded state")"
assert_contains "$redis_health" "\"status\":\"degraded\""
"${COMPOSE[@]}" up -d redis >/dev/null
wait_service_healthy redis
if ! wait_for_health healthy redis available "redis recovery" >/dev/null; then
  FAILURES+=("redis outage requires api-go restart before health returns to healthy")
  restart_host_api
  wait_for_health healthy redis available "redis recovery after api-go restart" >/dev/null
fi

echo "Checking degraded health when partner and notification channel are unavailable..."
"${COMPOSE[@]}" stop partner-recorder >/dev/null
partner_health="$(wait_for_health degraded partner_writeback degraded "partner degraded state")"
assert_contains "$partner_health" "\"notification_channel\":\"degraded\""
"${COMPOSE[@]}" up -d partner-recorder >/dev/null
wait_service_healthy partner-recorder
wait_http_ok "${PARTNER_RECORDER_URL}/healthz"
wait_for_health healthy partner_writeback available "partner recovery" >/dev/null

echo "Checking unavailable health when PostgreSQL is unavailable..."
"${COMPOSE[@]}" stop postgres >/dev/null
postgres_health="$(wait_for_health unavailable postgres unavailable "postgres unavailable state")"
assert_contains "$postgres_health" "\"status\":\"unavailable\""
"${COMPOSE[@]}" up -d postgres >/dev/null
wait_service_healthy postgres
if ! wait_for_health healthy postgres available "postgres recovery" >/dev/null; then
  FAILURES+=("postgres outage requires api-go restart before health returns to healthy")
  restart_host_api
  wait_for_health healthy postgres available "postgres recovery after api-go restart" >/dev/null
fi

if [[ "${#FAILURES[@]}" -gt 0 ]]; then
  printf 'Phase 5 I4 acceptance completed with confirmed recovery findings:\n' >&2
  printf ' - %s\n' "${FAILURES[@]}" >&2
  printf 'Measured bounded live timings: %s\n' "${PERF_METRICS[*]}" >&2
  exit 1
fi

printf 'Measured bounded live timings: %s\n' "${PERF_METRICS[*]}"
echo "Phase 5 I4 health, outage, security, and backup/restore checks passed."
