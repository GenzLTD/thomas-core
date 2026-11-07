#!/usr/bin/env bash
# thomas-core 服务器侧部署脚本（CI 经 SSH 调用，也可手动执行）
# 用法: deploy-thomas-core.sh <commit-sha>
# 形态: 宿主机 venv（仓 README 既定）；端口 5300；THOMAS_SCHEMA_SPLIT=1
#
# 纪律:
#   - 只写 ~/thomas/（releases / current / .venv / data / logs / bin），不碰 /opt、不碰生产库
#   - smoke 9/9 是硬门禁，不过就不切换 current
#   - 健康检查失败自动回滚到上一个 release
#   - 真实凭据只进 ~/thomas/.env（chmod 600，运维面维护，CI 不碰）
#   - 依赖一律钉版安装；禁 pip install 不带版本约束的包
#
# 前置:
#   - backend/requirements-core.pinned.txt 已入仓（R3 定版）
#   - ~/.ssh/deploy_thomas_core（只读 deploy key，公钥已入本机 authorized_keys）
#   - systemd 单元 thomas-core.service 已安装（sudo systemctl enable --now thomas-core 首次）
set -euo pipefail

SHA="${1:?usage: deploy-thomas-core.sh <commit-sha>}"
PYVER="${PYVER:-3.12}"            # 基线 Python（2026-11-07 从 3.10 升级：3.10 已 EOL；钉版四包曾卡 >=3.10 零余量）
PY_MODE="${PY_MODE:-deadsnakes}"  # 3.12 获取方式：deadsnakes=apt PPA（默认）| uv=静态二进制免 root
APP="$HOME/thomas"
SRC="$APP/src"
RELEASES="$APP/releases"
CURRENT="$APP/current"
VENV="$APP/.venv"
KEEP=5
PORT=5300

say() { echo -e "\n[deploy $(date '+%F %T')] $*"; }

# --- 0. 目录骨架 ---
mkdir -p "$RELEASES" "$APP/data" "$APP/logs" "$APP/bin"

# --- 1. 代码：只读 deploy key 拉取（服务器唯一 GitHub 凭据）---
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/deploy_thomas_core -o IdentitiesOnly=yes"
if [ ! -d "$SRC/.git" ]; then
  say "首次引导：clone thomas-core"
  GIT_SSH_COMMAND="$GIT_SSH_COMMAND -o StrictHostKeyChecking=accept-new" \
    git clone -q git@github.com:GenzLTD/thomas-core.git "$SRC"
fi
say "fetch $SHA"
# GitHub 只认完整 40 位 SHA 或分支名：缩写 SHA 先回退 fetch main，再本地 rev-parse 解析
git -C "$SRC" fetch -q origin "$SHA" 2>/dev/null || git -C "$SRC" fetch -q origin main
FULL="$(git -C "$SRC" rev-parse --verify -q "${SHA}^{commit}")" || FULL=""
if [ -z "$FULL" ]; then
  echo "FATAL: 无法解析 $SHA —— 缩写解析失败或该提交不在 main 上（dispatch 传旧 SHA 前先确认存在）"
  exit 1
fi
say "resolved: $SHA -> $FULL"
SHA="$FULL"

REL="$RELEASES/$SHA"
rm -rf "$REL"; mkdir -p "$REL"
git -C "$SRC" archive "$SHA" | tar -x -C "$REL"     # 干净导出，不带 .git

# --- 2. venv：首次含 Python $PYVER 并存安装（系统 3.10 不动，apt 依赖它）---
# Ubuntu 22.04 系统 Python 是 3.10；3.12 并存安装两条路：
#   deadsnakes：add-apt-repository ppa:deadsnakes/ppa（Launchpad 源，apt 原生管理，默认）
#   uv        ：静态二进制 + uv python install（无 root、无 PPA 信任；PY_MODE=uv）
if [ ! -x "$VENV/bin/python" ]; then
  say "首次引导：安装 Python $PYVER 并建 venv"
  if ! command -v "python$PYVER" >/dev/null 2>&1; then
    case "$PY_MODE" in
      deadsnakes)
        sudo apt-get update -y
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get update -y
        sudo apt-get install -y "python$PYVER" "python$PYVER-venv"
        ;;
      uv)
        command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        uv python install "$PYVER"
        uv venv --python "$PYVER" "$VENV"
        ;;
      *) echo "FATAL: 未知 PY_MODE=$PY_MODE（deadsnakes|uv）"; exit 1 ;;
    esac
  fi
  if [ ! -x "$VENV/bin/python" ]; then
    "python$PYVER" -m ensurepip --version >/dev/null 2>&1 || sudo apt-get install -y "python$PYVER-venv"
    "python$PYVER" -m venv "$VENV"
  fi
  "$VENV/bin/python" --version
fi

# --- 3. 钉版安装（源三级 fallback：腾讯内网 → 清华 → pypi.org）---
PIN="$REL/backend/requirements-core.pinned.txt"
[ -f "$PIN" ] || { echo "FATAL: 缺钉版文件 $PIN（先提交进仓）"; exit 1; }
install_with() { "$VENV/bin/pip" install -q --disable-pip-version-check -r "$PIN" "$@"; }
if install_with -i http://mirrors.tencentyun.com/pypi/simple --trusted-host mirrors.tencentyun.com; then
  say "pip source: tencent-internal"
elif install_with -i https://pypi.tuna.tsinghua.edu.cn/simple; then
  say "pip source: tsinghua"
elif install_with -i https://pypi.org/simple; then
  say "pip source: pypi.org"
else
  echo "FATAL: 三个源全部失败"; exit 1
fi

# --- 4. smoke 门禁（临时 SQLite / 清 Supabase+DeepSeek 变量 / 不联网 / 零业务风险）---
say "smoke 门禁"
( cd "$REL/backend" && "$VENV/bin/python" ../scripts/smoke_core.py )

# --- 5. 原子切换 + 重启 ---
say "切换 current → $SHA"
ln -sfn "$REL" "$CURRENT"
printf 'GIT_COMMIT=%s\n' "$SHA" > "$APP/deploy.env"
sudo systemctl restart thomas-core

# --- 6. 健康检查；失败自动回滚到上一个 release ---
ok=""
for _ in $(seq 1 15); do
  sleep 1
  if curl -sf -m 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -q thomas-core; then ok=1; break; fi
done
if [ -n "$ok" ]; then
  ls -1t "$RELEASES" | tail -n +$((KEEP+1)) | while read -r old; do rm -rf "$RELEASES/$old"; done
  say "deploy OK: $SHA"
else
  PREV=$(ls -1t "$RELEASES" | grep -v "^${SHA}$" | head -1 || true)
  if [ -n "$PREV" ]; then
    ln -sfn "$RELEASES/$PREV" "$CURRENT"
    printf 'GIT_COMMIT=%s\n' "$PREV" > "$APP/deploy.env"
    sudo systemctl restart thomas-core
    say "ROLLBACK → $PREV"
  fi
  say "health FAIL，日志尾部："
  tail -50 "$APP/logs/thomas-core.log" 2>/dev/null || true
  exit 1
fi
