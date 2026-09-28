#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [--resume <key>] <workdir> <ticket-path>\n' "$0" >&2
  exit 2
}

# 參數與 pi helper 相同（接續鍵，不含 --require-resume），改派時照抄即可；zcode 沒有可接續的 session，--resume 一律從零開始。
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
for template in "$receipt_template" "$prompt_template"; do
  [[ -f "$template" ]] || {
    printf 'skill template is missing: %s (freeze the whole skill directory, not just scripts/)\n' "$template" >&2
    exit 1
  }
done

# Credential file is runtime-only and intentionally excluded from static analysis.
# shellcheck disable=SC1091
source "$HOME"/.openclaw/secrets/glm-coding-plan.env

if [[ -z "${ZHIPU_API_KEY:-}" ]]; then
  printf 'Coding Plan credential is unavailable\n' >&2
  exit 1
fi

api_key=$ZHIPU_API_KEY
unset ZHIPU_API_KEY

zcode_bin="${ZCODE_CLI_BIN:-$HOME/.local/share/zcode/squashfs-root/resources/glm/zcode.cjs}"
[[ -f "$zcode_bin" ]] || {
  printf 'ZCode CLI is unavailable\n' >&2
  exit 1
}

# 送單指示正本在 templates/worker-prompt.md，pi 與 zcode 共用；這裡只代換佔位符。
# 引擎標籤也印在起跑行，經理照它填工單 claimed-by，不另抄模型名。
engine='zcode / GLM-5.3-Flash（Coding Plan）'
prompt=$(<"$prompt_template")
# 代換值一定要包雙引號：bash 5.2 的 patsub_replacement 會把未引號的 & 換成比對到的佔位符。
prompt=${prompt//'{{TICKET}}'/"$ticket"}
prompt=${prompt//'{{WORKDIR}}'/"$workdir"}
prompt=${prompt//'{{RECEIPT_TEMPLATE}}'/"$receipt_template"}
prompt=${prompt//'{{ENGINE}}'/"$engine"}

# 工人以乾淨環境啟動：不繼承呼叫端（經理 session）已匯出的 token 與業務憑證。
# 只留執行必需的變數；本機磁碟上的 secret 檔仍可讀，隔離的剩餘風險見 SKILL.md。
# 直接 unset 再 exec，不用 env -i：金鑰只在環境變數裡，不出現在任何程序的 argv。
keep=" HOME PATH USER LOGNAME LANG TERM TMPDIR XDG_RUNTIME_DIR DOCKER_HOST HTTPS_PROXY HTTP_PROXY NO_PROXY TZ "
for name in $(compgen -e); do
  [[ $keep == *" $name "* ]] || unset -v "$name" 2>/dev/null || true
done
export USER="${USER:-$(id -un)}" LOGNAME="${LOGNAME:-$(id -un)}" LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}"
export ANTHROPIC_API_KEY="$api_key"
unset api_key
export ZCODE_MODEL=GLM-5.3-Flash ZCODE_BASE_URL=https://open.bigmodel.cn/api/anthropic

# exec 沿用同一個 PID：經理用這行看工人是否還在跑（ps -o etime= -p <pid>）。
# proc_start 讓 wait-worker.sh 分得出這個 pid 後來是不是被別的程序重用了。
read -r proc_stat 2>/dev/null </proc/$$/stat || proc_stat=
read -ra proc_fields <<<"${proc_stat##*) }"
printf 'zcode worker start pid=%s engine=%s ticket=%s%s proc_start=%s at=%s\n' "$$" "$engine" "$ticket" "${chain:+ session=fresh(zcode cannot resume)}" \
  "${proc_fields[19]:-}" "$(TZ=Asia/Taipei date '+%F %T %z')" >&2
# 無頭工人不繼承呼叫端的 stdin：開著的 pipe／socket 會讓 CLI 一直等 EOF。
exec node "$zcode_bin" --prompt "$prompt" --cwd "$workdir" --mode yolo --no-color </dev/null
