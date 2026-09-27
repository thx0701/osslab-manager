#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s <workdir> <review-prompt-file>\n' "$0" >&2
  exit 2
fi

workdir=$1
prompt_file=$2
[[ -d "$workdir" && -f "$prompt_file" ]] || {
  printf 'workdir or review prompt is missing\n' >&2
  exit 2
}

prompt=$(<"$prompt_file")
printf 'reviewer pid=%s model=grok-4.7 effort=medium started=%s\n' \
  "$$" "$(TZ=Asia/Taipei date '+%Y-%m-%dT%H:%M:%S%:z')" >&2
# MCP 工具（瀏覽器、deja 等）不在 --tools 白名單內；dontAsk 遇到會取消整個回合、仍 exit 0，
# 報告就被截斷。明確 deny 讓呼叫被拒後模型繼續審查。
exec grok --model grok-4.7 --reasoning-effort medium \
  --tools Read,Grep --permission-mode dontAsk --deny 'MCPTool(*)' \
  --no-subagents --disable-web-search \
  --single "$prompt" --cwd "$workdir"
