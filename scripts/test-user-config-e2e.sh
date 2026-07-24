#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
TEST_PORT=18765
SERVER_LOG="$(mktemp /tmp/issuescope-user-config.XXXXXX.log)"
TEST_ENV_FILE="$(mktemp /tmp/issuescope-user-config.XXXXXX.env)"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$SERVER_LOG"
  rm -f "$TEST_ENV_FILE"
}
trap cleanup EXIT

cd "$BACKEND_DIR"
DATABASE_URL= \
LLM_API_BASE_URL=https://initial.example.com/v1 \
LLM_API_KEY=initial-test-key \
LLM_MODEL=initial-test-model \
GITHUB_TOKEN=initial-test-token \
GITHUB_WEBHOOK_SECRET=initial-test-webhook \
ISSUESCOPE_RUNTIME_ENV_FILE="$TEST_ENV_FILE" \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$TEST_PORT" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl --silent --fail "http://127.0.0.1:$TEST_PORT/api/users/config" >/dev/null; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    cat "$SERVER_LOG"
    exit 1
  fi
  sleep 1
done

if ! curl --silent --fail "http://127.0.0.1:$TEST_PORT/api/users/config" >/dev/null; then
  cat "$SERVER_LOG"
  echo "isolated backend did not become ready" >&2
  exit 1
fi

cd "$PROJECT_DIR/frontend"
TEST_ALLOW_CONFIG_MUTATION=1 \
TEST_API_BASE_URL="http://127.0.0.1:$TEST_PORT" \
  node tests/user-config-api.mjs
