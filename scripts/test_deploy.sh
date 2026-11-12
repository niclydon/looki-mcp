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
cp "$repo_root/.gitignore" "$seed/.gitignore"
mkdir -p "$seed/scripts"
cp "$repo_root/scripts/run_offline_tests.sh" "$seed/scripts/run_offline_tests.sh"
chmod +x "$seed/scripts/run_offline_tests.sh"
cp "$repo_root"/scripts/test_*.py "$seed/scripts/"
git -C "$seed" add requirements.txt .gitignore scripts/
git -C "$seed" commit -qm initial
git -C "$seed" remote add origin "$remote"
git -C "$seed" push -q -u origin main
git --git-dir="$remote" symbolic-ref HEAD refs/heads/main
git clone -q "$remote" "$service"
mkdir -p "$service/.venv/bin"
cat > "$service/.venv/bin/python" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$tmp/python.log"
case "\$*" in
  *"pip check"*) [[ -z "\${FAIL_PIP_CHECK:-}" ]] ;;
  "-c import main") [[ -z "\${FAIL_IMPORT:-}" ]] ;;
  *"test_"*".py"|*"compileall"*) [[ -z "\${FAIL_OFFLINE_GATE:-}" ]] ;;
esac
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
grep -q -- '-m pip check --disable-pip-version-check' "$tmp/python.log"
grep -qx -- '-c import main' "$tmp/python.log"
grep -q 'scripts/test_cache.py' "$tmp/python.log"
grep -q -- '-m compileall' "$tmp/python.log"
grep -q '^restart looki-mcp.service$' "$tmp/systemctl.log"
grep -q '^is-active --quiet looki-mcp.service$' "$tmp/systemctl.log"
[[ "$(cat "$service/.deployed-sha")" == "$(git -C "$service" rev-parse HEAD)" ]]
[[ -z "$(git -C "$service" status --porcelain)" ]]

# The deploy stamp must not trip the dirty-tree guard on the next deployment.
PATH="$bin:$PATH" LOOKI_MCP_SERVICE_DIR="$service" "$repo_root/scripts/deploy.sh" origin/main
[[ -z "$(git -C "$service" status --porcelain)" ]]

# OB-65573 / OB-69925: a venv that fails pip check or cannot import main.py,
# or a red offline test gate, aborts the deploy before the restart, so the
# old process keeps serving.
for failure in FAIL_IMPORT FAIL_PIP_CHECK FAIL_OFFLINE_GATE; do
  : > "$tmp/systemctl.log"
  if env "$failure=1" PATH="$bin:$PATH" LOOKI_MCP_SERVICE_DIR="$service" \
      "$repo_root/scripts/deploy.sh" origin/main 2> "$tmp/deploy.err"; then
    echo "deploy succeeded with $failure" >&2
    exit 1
  fi
  grep -q 'was not restarted' "$tmp/deploy.err"
  [[ ! -s "$tmp/systemctl.log" ]] || { echo "systemctl ran despite $failure" >&2; exit 1; }
done

echo "looki deploy test: ok"
