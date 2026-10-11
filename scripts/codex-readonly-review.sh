#!/usr/bin/env bash
set -euo pipefail
# bash 會把環境裡匯出的函式匯入，名叫 codex、grep 的函式會蓋過真的指令；先全部清掉。
for name in $(compgen -A function); do unset -f "$name"; done

[[ $# -eq 2 && -d "$1" && -f "$2" ]] || {
  printf 'usage: %s <workdir> <review-prompt-file>\n' "$0" >&2
  exit 2
}
workdir=$(readlink -f "$1")
prompt_file=$(readlink -f "$2")
command -v codex >/dev/null || {
  printf 'Codex CLI is unavailable\n' >&2
  exit 1
}
# 登入沿用 CODEX_HOME（預設 ~/.codex），不複製憑證：ChatGPT 登入刷新時舊 token 可能失效。
keep=' HOME PATH USER LOGNAME LANG TERM TMPDIR TZ HTTPS_PROXY HTTP_PROXY NO_PROXY CODEX_HOME '
for name in $(compgen -e); do
  [[ $keep == *" $name "* ]] || unset -v "$name" 2>/dev/null || true
done
model=gpt-6-astra effort=medium
# proc_start 讓 wait-worker.sh 分得出這個 pid 後來是不是被別的程序重用了。
read -r proc_stat 2>/dev/null </proc/$$/stat || proc_stat=
read -ra proc_fields <<<"${proc_stat##*) }"
printf 'reviewer pid=%s model=%s effort=%s started=%s proc_start=%s\n' \
  "$$" "$model" "$effort" "$(TZ=Asia/Taipei date '+%Y-%m-%dT%H:%M:%S%:z')" "${proc_fields[19]:-}" >&2

log=$(mktemp "${TMPDIR:-/tmp}/codex-review-log.XXXXXX")
report=$(mktemp "${TMPDIR:-/tmp}/codex-review-report.XXXXXX")
trap 'rm -f "$log" "$report"' EXIT
# 唯讀沙箱：shell 只能讀、不能寫、沒有網路；不載入 config.toml（MCP 工具、模型目錄等本機設定）、
# 關網路搜尋、不留 session 檔。prompt 走 stdin，不受參數長度限制。
# setsid 讓 codex 自成程序群組，取消時能連同它的子程序一起收掉，不碰呼叫端的群組。
setsid codex exec --ignore-user-config --ephemeral --skip-git-repo-check \
  --sandbox read-only --model gpt-6-astra -c model_reasoning_effort=medium -c 'web_search="disabled"' \
  --cd "$workdir" --output-last-message "$report" - <"$prompt_file" >/dev/null 2>"$log" &
child=$!
stop() {
  kill -TERM -- "-$child" 2>/dev/null || true
  for _ in {1..50}; do
    kill -0 -- "-$child" 2>/dev/null || break
    sleep 0.1
  done
  kill -KILL -- "-$child" 2>/dev/null || true
  wait "$child" 2>/dev/null || true
  exit 143
}
trap stop TERM INT HUP
rc=0
wait "$child" || rc=$?
trap - TERM INT HUP

fail() {
  tail -n 20 "$log" >&2
  printf 'Codex review %s\n' "$1" >&2
  exit 1
}
[[ $rc -eq 0 ]] || fail "failed (exit $rc)"
# Codex 開頭在兩條分隔線之間印實際設定；設定區不完整、欄位重複，或模型、沙箱、effort、工作目錄不符，
# 都不算有效審查。
settings=$(awk '/^--------$/ { if (++n == 2) exit; next } n == 1 { print } END { if (n < 2) exit 1 }' "$log") ||
  fail "printed no complete settings block"
for line in "model: $model" "sandbox: read-only" "approval: never" "reasoning effort: $effort" "workdir: $workdir"; do
  if [[ $(grep -c -- "^${line%%: *}: " <<<"$settings") -ne 1 ]] || ! grep -qxF -- "$line" <<<"$settings"; then
    fail "rejected: expected \"$line\" exactly once in its startup settings"
  fi
done
[[ -s $report ]] || fail "returned an empty report"
printf '%s\n' "$settings" >&2
printf '審查：codex / %s %s @ %s\n\n' "$model" "$effort" "$(TZ=Asia/Taipei date '+%Y-%m-%dT%H:%M:%S%:z')"
cat "$report"
# Codex 的最終回覆常不帶結尾換行；補上，免得存檔後黏到下一行。
[[ -z $(tail -c 1 "$report") ]] || printf '\n'
