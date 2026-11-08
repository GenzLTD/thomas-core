#!/usr/bin/env bash
# 从 GitHub 托管运行器登录新机。
# 不再下载 drone-ssh：那一步每次都向 GitHub Releases 拉二进制，504 时任务还没连上服务器就失败。
# 主机指纹仍只接受已经存好的 ECDSA P-256。扫描结果对不上就退出，不放宽检查。
set -euo pipefail

host="${DEPLOY106_HOST:-}"
user="${DEPLOY106_USER:-ubuntu}"
key_text="${DEPLOY106_SSH_KEY:-}"
expected="${DEPLOY106_HOST_FINGERPRINT:-}"
action="${1:-}"
sha="${2:-}"

if [ -z "$host" ] || [ -z "$key_text" ] || [ -z "$expected" ]; then
  echo "missing host, key, or fingerprint" >&2
  exit 1
fi

case "$action" in
  deploy)
    case "$sha" in
      [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]*) ;;
      *)
        echo "bad sha" >&2
        exit 1
        ;;
    esac
    if [ "${#sha}" -gt 40 ]; then
      echo "bad sha" >&2
      exit 1
    fi
    remote="set -e; ~/thomas/bin/deploy-thomas-core.sh ${sha}"
    ;;
  kernel)
    remote='set -euo pipefail; mkdir -p "$HOME/thomas/bin"; install -m 755 "$HOME/thomas/current/scripts/deploy-gfcc-kernel.sh" "$HOME/thomas/bin/deploy-gfcc-kernel.sh"; "$HOME/thomas/bin/deploy-gfcc-kernel.sh"'
    ;;
  *)
    echo "usage: ci-ssh.sh deploy <sha> | ci-ssh.sh kernel" >&2
    exit 1
    ;;
esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf '%s\n' "$key_text" > "$tmp/key"
chmod 600 "$tmp/key"

scanned=""
for _attempt in 1 2 3; do
  scanned=$(ssh-keyscan -t ecdsa -T 10 "$host" 2>/dev/null | grep -v '^#' || true)
  if [ -n "$scanned" ]; then
    break
  fi
  sleep 2
done
if [ -z "$scanned" ]; then
  echo "host key scan failed" >&2
  exit 1
fi

matched=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  fp=$(printf '%s\n' "$line" | ssh-keygen -lf - | awk 'NR==1 { print $2 }')
  if [ "$fp" = "$expected" ]; then
    matched="$line"
    break
  fi
done <<EOF
$scanned
EOF
if [ -z "$matched" ]; then
  echo "host key fingerprint mismatch" >&2
  exit 1
fi
printf '%s\n' "$matched" > "$tmp/known_hosts"

exec ssh \
  -i "$tmp/key" \
  -o BatchMode=yes \
  -o IdentitiesOnly=yes \
  -o ConnectTimeout=30 \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$tmp/known_hosts" \
  -o HostKeyAlgorithms=ecdsa-sha2-nistp256 \
  -o UpdateHostKeys=no \
  "${user}@${host}" \
  "$remote"
