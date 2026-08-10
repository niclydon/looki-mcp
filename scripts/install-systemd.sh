#!/usr/bin/env bash
set -euo pipefail

# Install the repo's systemd unit + restart-policy drop-in for looki-mcp.
# Pattern follows nexus-discord-gateway/scripts/deploy-service.sh steps 6/9.
# Does NOT restart the service — restart is a deliberate separate step.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_UNIT="looki-mcp.service"

cd "$ROOT_DIR"

if [[ ! -f "systemd/${SERVICE_UNIT}" ]]; then
  echo "FATAL: systemd/${SERVICE_UNIT} not found; run from the looki-mcp repository." >&2
  exit 1
fi

echo "[1/4] Installing systemd unit..."
sudo install -m 0644 "systemd/${SERVICE_UNIT}" "/etc/systemd/system/${SERVICE_UNIT}"

echo "[2/4] Installing restart-policy drop-in..."
sudo mkdir -p "/etc/systemd/system/${SERVICE_UNIT}.d"
sudo install -m 0644 "systemd/${SERVICE_UNIT}.d/restart-policy.conf" \
  "/etc/systemd/system/${SERVICE_UNIT}.d/restart-policy.conf"

echo "[3/4] Reloading systemd..."
sudo systemctl daemon-reload

echo "[4/4] Verifying repo and deployed files match..."
diff "systemd/${SERVICE_UNIT}" "/etc/systemd/system/${SERVICE_UNIT}"
diff "systemd/${SERVICE_UNIT}.d/restart-policy.conf" \
  "/etc/systemd/system/${SERVICE_UNIT}.d/restart-policy.conf"

echo "Install complete: repo and /etc/systemd/system are in sync."
