#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [--resume <key>] <workdir> <ticket-path>\n' "$0" >&2
  exit 2
}

# 參數與 pi helper 相同，改派時照抄即可。這支沒有可接續的 session，--resume 一律從零開始。
chain=
if [[ ${1:-} == --resume ]]; then
  [[ $# -ge 2 && $2 =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || usage
  chain=$2
  shift 2
fi
[[ $# -eq 2 ]] || usage

[[ -d "$1" && -f "$2" ]] || {
  printf 'workdir or ticket is missing\n' >&2
  exit 2
}
workdir=$(readlink -f "$1")
ticket=$(readlink -f "$2")
# 回執模板與送單指示在 skill 目錄的 templates/；凍結 helper 要複製整個 skill 目錄，只複製腳本會找不到它。
skill_dir=$(dirname "$(dirname "$(readlink -f "$0")")")
receipt_template=$skill_dir/templates/receipt.md
prompt_template=$skill_dir/templates/worker-prompt.md
runner=$skill_dir/scripts/claude-haiku-run.py
for required in "$receipt_template" "$prompt_template" "$runner"; do
  [[ -f "$required" ]] || {
    printf 'skill template is missing: %s (freeze the whole skill directory, not just scripts/)\n' "$required" >&2
    exit 1
  }
done

# 訂閱登入在 Claude Code 自己的憑證檔，不讀 API key。內容不印、不進 argv。
credential=$HOME/.claude/.credentials.json
[[ -f $credential && -s $credential ]] || {
  printf 'subscription credential is unavailable\n' >&2
  exit 1
}
claude_bin=${CLAUDE_BIN:-$HOME/.local/bin/claude}
[[ -x $claude_bin ]] || {
  printf 'Claude CLI is unavailable\n' >&2
  exit 1
}

# 送單指示正本在 templates/worker-prompt.md；這裡只代換佔位符。
# 引擎標籤也印在起跑行，經理照它填工單 claimed-by，不另抄模型名。
engine='claude / claude-haiku-5-5（Pro）'
prompt=$(<"$prompt_template")
# 代換值一定要包雙引號：bash 5.2 的 patsub_replacement 會把未引號的 & 換成比對到的佔位符。
prompt=${prompt//'{{TICKET}}'/"$ticket"}
prompt=${prompt//'{{WORKDIR}}'/"$workdir"}
prompt=${prompt//'{{RECEIPT_TEMPLATE}}'/"$receipt_template"}
prompt=${prompt//'{{ENGINE}}'/"$engine"}

# 私人設定目錄只放憑證副本，避免讀到使用者設定裡釘死的模型與 skill。跑完刪掉。
state=$HOME/.local/state/osslab-manager/claude-haiku
mkdir -p "$state"
chmod 700 "$state"
config_dir=$(mktemp -d "$state/run-XXXXXXXX")
python_pid=
cleanup() {
  set +e
  if [[ -n ${python_pid:-} ]]; then
    kill -TERM "$python_pid" 2>/dev/null || true
    wait "$python_pid" 2>/dev/null || true
  fi
  if [[ -n ${config_dir:-} ]]; then
    rm -rf -- "$config_dir"
  fi
}
trap cleanup EXIT
chmod 700 "$config_dir"
cp -- "$credential" "$config_dir/.credentials.json"
chmod 600 "$config_dir/.credentials.json"

# 工人以乾淨環境啟動：不繼承呼叫端已匯出的 token 與業務憑證。
# 不設置 ANTHROPIC_API_KEY 或 CLAUDE_CODE_OAUTH_TOKEN，否則會離開目前的訂閱登入。
keep=" HOME PATH USER LOGNAME LANG TERM TMPDIR XDG_RUNTIME_DIR DOCKER_HOST HTTPS_PROXY HTTP_PROXY NO_PROXY TZ "
for name in $(compgen -e); do
  [[ $keep == *" $name "* ]] || unset -v "$name" 2>/dev/null || true
done
export USER="${USER:-$(id -un)}" LOGNAME="${LOGNAME:-$(id -un)}" LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}"
unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN || true
export CLAUDE_CONFIG_DIR=$config_dir CLAUDE_CODE_SAFE_MODE=1

# 不 exec：這個 shell 要等子程序結束後刪掉憑證副本。起跑行的 pid 是這支 helper。
read -r proc_stat 2>/dev/null </proc/$$/stat || proc_stat=
read -ra proc_fields <<<"${proc_stat##*) }"
printf 'claude worker start pid=%s engine=%s ticket=%s%s proc_start=%s at=%s\n' "$$" "$engine" "$ticket" "${chain:+ session=fresh(claude cannot resume)}" \
  "${proc_fields[19]:-}" "$(TZ=Asia/Taipei date '+%F %T %z')" >&2
python3 "$runner" "$workdir" "$prompt" "$claude_bin" < /dev/null &
python_pid=$!
set +e
wait "$python_pid"
rc=$?
set -e
python_pid=
exit "$rc"
