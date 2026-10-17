#!/usr/bin/env bash
# Deploy looki-mcp to its git-in-place service checkout.
set -euo pipefail

SERVICE_DIR="${LOOKI_MCP_SERVICE_DIR:-/services/looki-mcp}"
SERVICE_UNIT="${LOOKI_MCP_SERVICE_UNIT:-looki-mcp.service}"
REF="${1:-origin/main}"

log() { printf '[looki-mcp-deploy] %s\n' "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ -d "$SERVICE_DIR/.git" ]] || die "$SERVICE_DIR is not a git checkout"
[[ -x "$SERVICE_DIR/.venv/bin/python" ]] || die "$SERVICE_DIR/.venv/bin/python is missing"

cd "$SERVICE_DIR"
git remote get-url origin >/dev/null 2>&1 || die "origin remote is missing"
[[ -z "$(git status --porcelain)" ]] || die "$SERVICE_DIR has local changes; refusing to overwrite them"

log "fetching origin"
git fetch origin
git rev-parse --verify "${REF}^{commit}" >/dev/null 2>&1 || die "ref does not resolve to a commit: $REF"
git checkout --detach "$REF"
SHA="$(git rev-parse HEAD)"
log "checked out $SHA"

log "installing Python requirements"
"$SERVICE_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r requirements.txt

# Check the installed venv before touching the running service: an in-place
# upgrade can leave a package unimportable (fastmcp 3.x -> 4.x split, OB-65573),
# and restarting onto it is downtime. On failure the old process keeps serving.
log "checking installed requirements and the service import"
"$SERVICE_DIR/.venv/bin/python" -m pip check --disable-pip-version-check \
  || die "pip check failed; $SERVICE_UNIT was not restarted"
"$SERVICE_DIR/.venv/bin/python" -c 'import main' \
  || die "main.py does not import in the service venv; $SERVICE_UNIT was not restarted"

# Persist the least-privilege mode required by the service owner. Files below
# the directory keep their existing executable/readability modes.
chmod 750 "$SERVICE_DIR"

log "restarting $SERVICE_UNIT"
sudo systemctl restart "$SERVICE_UNIT"
sudo systemctl is-active --quiet "$SERVICE_UNIT"

PORT="$(sed -nE 's/^[[:space:]]*LOOKI_PORT=([0-9]+)[[:space:]]*$/\1/p' .env | tail -1)"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "LOOKI_PORT is missing or non-numeric in $SERVICE_DIR/.env"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
log "checking $HEALTH_URL"
health_json="$(curl --fail --silent --show-error --retry 12 --retry-delay 1 --retry-connrefused "$HEALTH_URL")"
python3 -c 'import json,sys; body=json.load(sys.stdin); assert body.get("status") == "ok" and body.get("server") == "looki-mcp"' <<< "$health_json" \
  || die "health response did not identify a healthy looki-mcp server"

printf '%s\n' "$SHA" > .deployed-sha
log "deploy complete; health=ok sha=$SHA mode=$(stat -c '%a' "$SERVICE_DIR")"
