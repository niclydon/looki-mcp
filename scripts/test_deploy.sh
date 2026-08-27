#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

remote="$tmp/remote.git"
seed="$tmp/seed"
service="$tmp/service"
bin="$tmp/bin"
mkdir -p "$bin"

git init --bare -q "$remote"
git init -q -b main "$seed"
git -C "$seed" config user.email test@example.invalid
git -C "$seed" config user.name test
printf 'fastmcp\n' > "$seed/requirements.txt"
printf '.env\n.venv/\n.deployed-sha\n' > "$seed/.gitignore"
git -C "$seed" add requirements.txt .gitignore
git -C "$seed" commit -qm initial
git -C "$seed" remote add origin "$remote"
git -C "$seed" push -q -u origin main
git --git-dir="$remote" symbolic-ref HEAD refs/heads/main
git clone -q "$remote" "$service"
mkdir -p "$service/.venv/bin"
cat > "$service/.venv/bin/python" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$tmp/python.log"
EOF
chmod +x "$service/.venv/bin/python"
printf 'LOOKI_PORT=7861\n' > "$service/.env"

cat > "$bin/sudo" <<'EOF'
#!/usr/bin/env bash
exec "$@"
EOF
cat > "$bin/systemctl" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$tmp/systemctl.log"
EOF
cat > "$bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '{"status":"ok","server":"looki-mcp"}\n'
EOF
chmod +x "$bin/"*

PATH="$bin:$PATH" LOOKI_MCP_SERVICE_DIR="$service" "$repo_root/scripts/deploy.sh" origin/main

[[ "$(stat -c '%a' "$service")" == "750" ]]
grep -q -- '-m pip install --disable-pip-version-check -r requirements.txt' "$tmp/python.log"
grep -q '^restart looki-mcp.service$' "$tmp/systemctl.log"
grep -q '^is-active --quiet looki-mcp.service$' "$tmp/systemctl.log"
[[ "$(cat "$service/.deployed-sha")" == "$(git -C "$service" rev-parse HEAD)" ]]

echo "looki deploy test: ok"
