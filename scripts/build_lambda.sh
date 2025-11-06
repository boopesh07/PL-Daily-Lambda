#!/usr/bin/env bash
set -euo pipefail

echo "[build_lambda] Starting Lambda build."

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

: "${PYTHON:=python3}"
: "${LAMBDA_BUILD_DIR:=build/lambda}"
: "${LAMBDA_ZIP_PATH:=build/pl_daily_snapshot.zip}"

rm -rf "${LAMBDA_BUILD_DIR}"
mkdir -p "${LAMBDA_BUILD_DIR}"

echo "[build_lambda] Installing dependencies into ${LAMBDA_BUILD_DIR}"
"${PYTHON}" -m pip install --upgrade pip >/dev/null
"${PYTHON}" -m pip install -r requirements.txt --target "${LAMBDA_BUILD_DIR}" >/dev/null

echo "[build_lambda] Copying source files."
cp -R src "${LAMBDA_BUILD_DIR}/"

ZIP_DIR=$(dirname "${LAMBDA_ZIP_PATH}")
mkdir -p "${ZIP_DIR}"
rm -f "${LAMBDA_ZIP_PATH}"

echo "[build_lambda] Creating zip artifact at ${LAMBDA_ZIP_PATH}"
pushd "${LAMBDA_BUILD_DIR}" >/dev/null
zip -qr "../$(basename "${LAMBDA_ZIP_PATH}")" .
popd >/dev/null

echo "[build_lambda] Build complete."
