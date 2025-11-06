#!/usr/bin/env bash
set -euo pipefail

echo "[deploy_lambda] Starting Lambda deployment."

if [[ -f ".env" ]]; then
  ENV_EXPORTS=$(python3 - <<'PY'
from shlex import quote

env_lines = []
with open(".env", "r", encoding="utf-8") as fh:
    for raw in fh:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        env_lines.append(f'export {key}={quote(value)}')

print("\n".join(env_lines))
PY
)
  if [[ -n "${ENV_EXPORTS}" ]]; then
    eval "${ENV_EXPORTS}"
  fi
fi

: "${AWS_REGION:=us-east-1}"
: "${AWS_PROFILE:=}"
: "${LAMBDA_FUNCTION_NAME:?LAMBDA_FUNCTION_NAME env required}"
: "${LAMBDA_ZIP_PATH:=build/pl_daily_snapshot.zip}"
: "${LAMBDA_ROLE_ARN:=}"
: "${LAMBDA_RUNTIME:=python3.11}"
: "${LAMBDA_HANDLER:=src.lambda_handler.handler}"
: "${LAMBDA_TIMEOUT:=900}"
: "${LAMBDA_MEMORY_SIZE:=512}"
: "${EVENTBRIDGE_RULE_NAME:=pl-daily-pl-755pm}"
: "${EVENTBRIDGE_TIMEZONE:=America/New_York}"
: "${EVENTBRIDGE_CRON:=cron(55 19 * * ? *)}"

if [[ ! -f "${LAMBDA_ZIP_PATH}" ]]; then
  echo "[deploy_lambda] ERROR: Lambda artifact not found at ${LAMBDA_ZIP_PATH}" >&2
  echo "Run scripts/build_lambda.sh first." >&2
  exit 1
fi

AWS_CLI_FLAGS=(--region "${AWS_REGION}")
if [[ -n "${AWS_PROFILE:-}" ]]; then
  if [[ "${AWS_PROFILE}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    AWS_CLI_FLAGS+=(--profile "${AWS_PROFILE}")
  else
    echo "[deploy_lambda] WARNING: Ignoring invalid AWS_PROFILE value '${AWS_PROFILE}'."
  fi
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "[deploy_lambda] ERROR: aws CLI not found in PATH." >&2
  exit 1
fi

set +e
aws "${AWS_CLI_FLAGS[@]}" lambda get-function --function-name "${LAMBDA_FUNCTION_NAME}" >/dev/null 2>&1
GET_FN_STATUS=$?
set -e

wait_for_active() {
  echo "[deploy_lambda] Waiting for function ${LAMBDA_FUNCTION_NAME} to become active."
  aws "${AWS_CLI_FLAGS[@]}" lambda wait function-exists --function-name "${LAMBDA_FUNCTION_NAME}"
  aws "${AWS_CLI_FLAGS[@]}" lambda wait function-active-v2 --function-name "${LAMBDA_FUNCTION_NAME}"
}

if [[ ${GET_FN_STATUS} -ne 0 ]]; then
  if [[ -z "${LAMBDA_ROLE_ARN}" ]]; then
    echo "[deploy_lambda] ERROR: Lambda function does not exist and LAMBDA_ROLE_ARN is not provided to create it." >&2
    exit 1
  fi
  echo "[deploy_lambda] Creating Lambda function ${LAMBDA_FUNCTION_NAME}"
  aws "${AWS_CLI_FLAGS[@]}" lambda create-function \
    --function-name "${LAMBDA_FUNCTION_NAME}" \
    --runtime "${LAMBDA_RUNTIME}" \
    --role "${LAMBDA_ROLE_ARN}" \
    --handler "${LAMBDA_HANDLER}" \
    --timeout "${LAMBDA_TIMEOUT}" \
    --memory-size "${LAMBDA_MEMORY_SIZE}" \
    --zip-file "fileb://${LAMBDA_ZIP_PATH}"
  wait_for_active
else
  echo "[deploy_lambda] Updating function code for ${LAMBDA_FUNCTION_NAME}"
  aws "${AWS_CLI_FLAGS[@]}" lambda update-function-code \
    --function-name "${LAMBDA_FUNCTION_NAME}" \
    --zip-file "fileb://${LAMBDA_ZIP_PATH}" \
    >/dev/null
  wait_for_active

  echo "[deploy_lambda] Updating function configuration"
  aws "${AWS_CLI_FLAGS[@]}" lambda update-function-configuration \
    --function-name "${LAMBDA_FUNCTION_NAME}" \
    --timeout "${LAMBDA_TIMEOUT}" \
    --memory-size "${LAMBDA_MEMORY_SIZE}" \
    --handler "${LAMBDA_HANDLER}" \
    --runtime "${LAMBDA_RUNTIME}" \
    >/dev/null
  wait_for_active
fi

ENV_JSON=$(python3 - <<'PY'
import json
import os

keys = [
    "POLYGON_API_KEY",
    "REDIS_URL",
    "REDIS_TOKEN",
    "INCLUDE_OTC",
    "TICKER_BATCH_SIZE",
    "SNAPSHOT_CONCURRENCY",
    "TICKER_LIMIT",
    "REDIS_PIPELINE_SIZE",
    "REDIS_KEY_PREFIX",
    "REDIS_TTL_SECONDS",
    "HTTP_CONNECT_TIMEOUT",
    "HTTP_READ_TIMEOUT",
    "PL_TIMEZONE",
]
payload = {k: os.environ[k] for k in keys if os.environ.get(k)}
print(json.dumps({"Variables": payload}))
PY
)

if [[ "${ENV_JSON}" != '{"Variables":{}}' ]]; then
  echo "[deploy_lambda] Updating environment variables."
  aws "${AWS_CLI_FLAGS[@]}" lambda update-function-configuration \
    --function-name "${LAMBDA_FUNCTION_NAME}" \
    --environment "${ENV_JSON}" \
    >/dev/null
  wait_for_active
fi

FUNCTION_ARN=$(aws "${AWS_CLI_FLAGS[@]}" lambda get-function --function-name "${LAMBDA_FUNCTION_NAME}" --query 'Configuration.FunctionArn' --output text)

echo "[deploy_lambda] Ensuring EventBridge rule ${EVENTBRIDGE_RULE_NAME}"
CLI_VERSION=$(aws --version 2>&1)
PUT_RULE_CMD=(aws "${AWS_CLI_FLAGS[@]}" events put-rule
  --name "${EVENTBRIDGE_RULE_NAME}"
  --schedule-expression "${EVENTBRIDGE_CRON}"
  --state ENABLED
  --description "Daily 7:55 PM ${EVENTBRIDGE_TIMEZONE} trigger for ${LAMBDA_FUNCTION_NAME}"
)
if [[ -n "${EVENTBRIDGE_TIMEZONE}" && "${CLI_VERSION}" == aws-cli\/2* ]]; then
  PUT_RULE_CMD+=(--schedule-expression-timezone "${EVENTBRIDGE_TIMEZONE}")
elif [[ -n "${EVENTBRIDGE_TIMEZONE}" ]]; then
  echo "[deploy_lambda] WARNING: AWS CLI v1 detected; timezone support not available. Using UTC schedule."
fi
PUT_RULE_CMD+=(--query 'RuleArn' --output text)
RULE_ARN=$("${PUT_RULE_CMD[@]}")

echo "[deploy_lambda] Adding Lambda invoke permission for EventBridge."
aws "${AWS_CLI_FLAGS[@]}" lambda add-permission \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --statement-id "${EVENTBRIDGE_RULE_NAME}-invoke" \
  --action "lambda:InvokeFunction" \
  --principal events.amazonaws.com \
  --source-arn "${RULE_ARN}" \
  >/dev/null 2>&1 || true

echo "[deploy_lambda] Linking rule to Lambda target."
aws "${AWS_CLI_FLAGS[@]}" events put-targets \
  --rule "${EVENTBRIDGE_RULE_NAME}" \
  --targets "Id"="lambda","Arn"="${FUNCTION_ARN}" \
  >/dev/null

echo "[deploy_lambda] Deployment complete."
