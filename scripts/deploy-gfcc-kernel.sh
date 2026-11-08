#!/usr/bin/env bash
# gfcc-kernel 装到新机。口径对齐 Vultr 2026-10-18 的引入（先预发、再进基座）：
#   独立进程、独立 SQLite、只听 127.0.0.1:5211，不进 nginx，不切公网域名。
# 与 thomas-core 分开：不写 ~/thomas/current，不碰 5300，不读 looma.db。
# 版本取核仓当前钉子 contracts/gfcc/SOURCE.json 的 commit（v1.6.1 起含流向门）。
# 跨境出站保持关闭：GFCC_EGRESS_DEST_REGION 强制为空。
# 凭据只在 ~/gfcc-kernel/.env（chmod 600）。本脚本不写密钥。
# SIGNAL_INGEST_SECRET 必须已有，避免 no-auth。ETHOS_AUTH_SECRET 可空（stub，与当年预发相同，因为这次不开公网）。
set -euo pipefail

APP="${GFCC_KERNEL_HOME:-$HOME/gfcc-kernel}"
PIN_FILE="${GFCC_PIN_FILE:-$HOME/thomas/current/contracts/gfcc/SOURCE.json}"
SHA_ARG="${1:-}"
PYVER="${PYVER:-3.12}"
PORT=5211
KEEP=3

say() { echo -e "\n[gfcc-kernel $(date '+%F %T')] $*"; }

python_of() {
  if [ -x "$HOME/thomas/.venv/bin/python" ]; then
    echo "$HOME/thomas/.venv/bin/python"
  elif command -v "python$PYVER" >/dev/null 2>&1; then
    command -v "python$PYVER"
  else
    echo ""
  fi
}

read_env() {
  python3 - "$APP/.env" "$1" <<'PY'
import sys
path, key = sys.argv[1], sys.argv[2]
value = ""
for raw in open(path, encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, rest = line.split("=", 1)
    if name.strip() == key:
        value = rest.strip().strip("'\"")
print(value)
PY
}

# --- 0. 钉子与凭据。缺了就停，不启动半套进程 ---
[ -f "$PIN_FILE" ] || { echo "FATAL: 找不到钉子 $PIN_FILE"; exit 1; }
if [ -n "$SHA_ARG" ]; then
  SHA="$SHA_ARG"
else
  SHA="$(python3 - "$PIN_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["commit"])
PY
)"
fi
[ -f "$APP/.env" ] || { echo "FATAL: 缺少 $APP/.env 。写入 SIGNAL_INGEST_SECRET（必填）和 ETHOS_AUTH_SECRET（可空），chmod 600。本脚本不代写。"; exit 1; }
mode="$(stat -c '%a' "$APP/.env" 2>/dev/null || stat -f '%OLp' "$APP/.env")"
case "$mode" in
  600|400) ;;
  *) echo "FATAL: $APP/.env 权限是 $mode，需要 600"; exit 1 ;;
esac
if [ -z "$(read_env SIGNAL_INGEST_SECRET)" ]; then
  echo "FATAL: SIGNAL_INGEST_SECRET 为空。空密钥会让信号入口进入 no-auth。"
  exit 1
fi
if [ -n "$(read_env GFCC_EGRESS_DEST_REGION)" ]; then
  echo "FATAL: .env 写了 GFCC_EGRESS_DEST_REGION。这次引入不出境，请先清空该键。"
  exit 1
fi
if [ -z "$(read_env ETHOS_AUTH_SECRET)" ]; then
  say "ETHOS_AUTH_SECRET 为空：stub 鉴权。未开公网，与当年预发引入相同。"
fi

mkdir -p "$APP/releases" "$APP/data" "$APP/logs" "$APP/bin" "$APP/src"

# --- 1. 公开仓按钉子取源码。deploy key 只属于 thomas-core，这里走 HTTPS ---
SRC="$APP/src"
if [ ! -d "$SRC/.git" ]; then
  say "首次 clone gfcc"
  git clone -q https://github.com/GenzLTD/gfcc.git "$SRC"
fi
say "fetch $SHA"
git -C "$SRC" fetch -q origin "$SHA" 2>/dev/null || git -C "$SRC" fetch -q origin main
FULL="$(git -C "$SRC" rev-parse --verify -q "${SHA}^{commit}")" || FULL=""
if [ -z "$FULL" ]; then
  echo "FATAL: 无法解析 gfcc $SHA"
  exit 1
fi
SHA="$FULL"
REL="$APP/releases/$SHA"
if [ ! -f "$REL/services/gfcc_kernel/pyproject.toml" ]; then
  rm -rf "$REL"
  mkdir -p "$REL"
  git -C "$SRC" archive "$SHA" | tar -x -C "$REL"
fi

# --- 2. 已是这个钉子且健康：不重启 thomas，也不再装一遍 ---
health_fields() {
  curl -sf -m 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null | python3 -c 'import json,sys
try:
    data=json.loads(sys.stdin.read() or "{}")
except Exception:
    data={}
print(data.get("service",""))
print(data.get("store",""))'
}
if [ "$(readlink -f "$APP/current" 2>/dev/null || true)" = "$(readlink -f "$REL")" ]; then
  running="$(health_fields || true)"
  if [ "$(printf '%s\n' "$running" | sed -n '1p')" = "gfcc_kernel" ] \
     && [ "$(printf '%s\n' "$running" | sed -n '2p')" = "sqlite" ]; then
    say "already running $SHA"
    exit 0
  fi
fi

# --- 3. 端口必须是我们自己的，或者还没人听 ---
if curl -sf -m 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  if ! systemctl is-active --quiet gfcc-kernel 2>/dev/null; then
    echo "FATAL: 127.0.0.1:${PORT} 已有进程，但不是 systemd 单元 gfcc-kernel。先确认再装。"
    exit 1
  fi
fi

# --- 4. venv。优先借用 thomas 已装好的 Python 3.12，不另开一套系统包 ---
PY="$(python_of)"
[ -n "$PY" ] || { echo "FATAL: 没有 Python $PYVER（thomas venv 也不在）"; exit 1; }
if [ ! -x "$APP/.venv/bin/python" ]; then
  say "创建 venv"
  "$PY" -m venv "$APP/.venv"
fi
install_with() { "$APP/.venv/bin/pip" install -q --disable-pip-version-check "$@"; }
say "安装 ethos + gfcc_kernel @ $SHA"
install_pair() {
  install_with "$@" "$REL/services/ethos" \
    && install_with "$@" "$REL/services/gfcc_kernel"
}
if install_pair -i http://mirrors.tencentyun.com/pypi/simple --trusted-host mirrors.tencentyun.com; then
  say "pip source: tencent-internal"
elif install_pair -i https://pypi.tuna.tsinghua.edu.cn/simple; then
  say "pip source: tsinghua"
elif install_pair -i https://pypi.org/simple; then
  say "pip source: pypi.org"
else
  echo "FATAL: ethos / gfcc_kernel 安装失败"
  exit 1
fi
site="$("$APP/.venv/bin/python" -c 'import gfcc_kernel, os; print(os.path.dirname(gfcc_kernel.__file__))')"
cp -a "$REL/services/gfcc_kernel/src/gfcc_kernel/static" "$site/"

# --- 5. 启动脚本与单元。出站变量在脚本里强制清空，.env 不能把它打开 ---
cat > "$APP/bin/run-gfcc-kernel.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export STORE_PROVIDER=sqlite
export STORE_DB_PATH="$APP/data/memory.db"
export CIRCLE_FLOW_PROVIDER=sqlite
export CIRCLE_FLOW_DB="$APP/data/circle_flow.db"
export ETHOS_AUDIT_DB="$APP/logs/audit.db"
export LLM_PROVIDER=stub
export GFCC_MODE=gfcc.default
export GFCC_EGRESS_DEST_REGION=
export GFCC_SOURCE_REGION=
export PYTHONUNBUFFERED=1
exec "$APP/.venv/bin/uvicorn" gfcc_kernel.app:app --host 127.0.0.1 --port $PORT
EOF
chmod 755 "$APP/bin/run-gfcc-kernel.sh"

unit_user="$(id -un)"
unit_group="$(id -gn)"
cat > "$APP/gfcc-kernel.service" <<EOF
[Unit]
Description=gfcc-kernel localhost :$PORT
After=network.target

[Service]
Type=simple
User=$unit_user
Group=$unit_group
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
ExecStart=$APP/bin/run-gfcc-kernel.sh
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
sudo cp "$APP/gfcc-kernel.service" /etc/systemd/system/gfcc-kernel.service
sudo systemctl daemon-reload
sudo systemctl enable gfcc-kernel >/dev/null

# --- 6. 切换这个服务自己的 current，失败回到上一份 ---
say "切换 current → $SHA"
ln -sfn "$REL" "$APP/current"
sudo systemctl restart gfcc-kernel

ok=""
service=""
store=""
for _ in $(seq 1 20); do
  sleep 1
  body="$(curl -sf -m 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null || true)"
  fields="$(printf '%s' "$body" | python3 -c 'import json,sys
try:
    data=json.loads(sys.stdin.read() or "{}")
except Exception:
    data={}
print(data.get("service",""))
print(data.get("store",""))')"
  service="$(printf '%s\n' "$fields" | sed -n '1p')"
  store="$(printf '%s\n' "$fields" | sed -n '2p')"
  if [ "$service" = "gfcc_kernel" ] && [ "$store" = "sqlite" ]; then
    ok=1
    break
  fi
done
if [ -n "$ok" ]; then
  if command -v ss >/dev/null 2>&1; then
    listeners="$(ss -ltn | grep ":${PORT} " || true)"
    if ! printf '%s\n' "$listeners" | grep -q "127.0.0.1:${PORT}"; then
      echo "FATAL: 健康但没有只听 127.0.0.1:${PORT}"
      exit 1
    fi
    if printf '%s\n' "$listeners" | grep -Eq "0\.0\.0\.0:${PORT}|\\*:${PORT}"; then
      echo "FATAL: ${PORT} 没有收在回环上"
      exit 1
    fi
  fi
  ls -1t "$APP/releases" | tail -n +$((KEEP+1)) | while read -r old; do rm -rf "$APP/releases/$old"; done
  say "kernel OK: $SHA  127.0.0.1:${PORT}  egress=closed"
  exit 0
fi

PREV="$(ls -1t "$APP/releases" | grep -v "^${SHA}$" | head -1 || true)"
if [ -n "$PREV" ] && [ -d "$APP/releases/$PREV" ]; then
  ln -sfn "$APP/releases/$PREV" "$APP/current"
  sudo systemctl restart gfcc-kernel
  say "ROLLBACK → $PREV"
else
  sudo systemctl stop gfcc-kernel || true
fi
say "health FAIL service=${service:-empty} store=${store:-empty}"
sudo journalctl -u gfcc-kernel -n 40 --no-pager || true
exit 1
