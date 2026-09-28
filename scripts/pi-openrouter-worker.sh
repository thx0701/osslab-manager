#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [--resume <chain>] <workdir> <ticket-path>\n' "$0" >&2
  exit 2
}

# --resume <鏈名>：同一條未提交工單鏈的下一輪接續上一輪 pi 的記憶，省掉重讀 repo。
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
# 回執模板在 skill 目錄的 templates/；凍結 helper 要複製整個 skill 目錄，只複製腳本會找不到它。
skill_dir=$(dirname "$(dirname "$(readlink -f "$0")")")
receipt_template=$skill_dir/templates/receipt.md
[[ -f "$receipt_template" ]] || {
  printf 'receipt template is missing: %s (freeze the whole skill directory, not just scripts/)\n' "$receipt_template" >&2
  exit 1
}

# Credential file is runtime-only and intentionally excluded from static analysis.
# shellcheck disable=SC1091
source "$HOME"/.openclaw/secrets/openrouter.env

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  printf 'OpenRouter credential is unavailable\n' >&2
  exit 1
fi

api_key=$OPENROUTER_API_KEY
unset OPENROUTER_API_KEY

pi_bin=$(command -v pi) || { printf 'pi CLI is unavailable\n' >&2; exit 1; }

# 接續只在：workdir 是 git 工作樹、鏈起點之後 HEAD 沒變（還沒提交）、上一輪確實留下 pi session、
# 且最多接續 2 次；其餘一律從零開始。放在憑證與 CLI 檢查之後，啟動前就失敗的派工不佔次數。
# session 目錄帶 workdir 雜湊，同名鏈在不同 worktree 不會串到彼此的記憶。
session_args=(--no-session)
session_state=
resume_note=
if [[ -n $chain ]]; then
  if ! git -C "$workdir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    session_state='fresh(not a git work tree)'
  elif ! head=$(git -C "$workdir" rev-parse --verify -q HEAD 2>/dev/null); then
    session_state='fresh(no HEAD commit)'
  else
    sessions=$HOME/.local/state/osslab-manager/pi-sessions
    session_dir=$sessions/$chain-$(printf '%s' "$workdir" | sha256sum | cut -c1-12)
    mkdir -p "$sessions"
    # 目錄建立是原子的：兩個派工同時起跑時，只有一個寫起點。
    if mkdir -m 700 "$session_dir" 2>/dev/null; then
      printf '%s\n' "$head" >"$session_dir/base-head"
      printf '0\n' >"$session_dir/resumes"
    fi
    base=
    resumes=
    read -r base 2>/dev/null <"$session_dir/base-head" || true
    read -r resumes 2>/dev/null <"$session_dir/resumes" || true
    if [[ $base != "$head" ]]; then
      session_state="fresh(HEAD changed since chain start ${base:0:12})"
    elif [[ ! $resumes =~ ^[0-9]+$ ]]; then
      session_state='fresh(invalid resume counter)'
    elif ! compgen -G "$session_dir/*_$chain.jsonl" >/dev/null; then
      session_args=(--session-dir "$session_dir" --session-id "$chain")
      session_state="new(base ${head:0:12})"
    elif (( resumes >= 2 )); then
      session_state='fresh(resume limit 2 reached)'
    else
      printf '%s\n' "$((resumes + 1))" >"$session_dir/resumes"
      session_args=(--session-dir "$session_dir" --session-id "$chain")
      session_state="resumed($((resumes + 1))/2 base ${head:0:12})"
      resume_note="這是同一工單鏈的接續回合，你看得到上一輪的對話。上一輪的記憶不是證據，只是線索：先重讀這張工單與 git diff HEAD；記憶和工單或目前檔案衝突時，以工單與檔案為準；查證只在 workdir 裡做，不要為了核對記憶去搜 workdir 以外的路徑；不要沿用上一輪自製的 fixture 或測試資料，照這張工單的規定重建；回執第 4 節列出你捨棄的上一輪假設。"
    fi
  fi
fi

prompt="你是這張工單的執行者，無頭運行，沒有人能回答你的問題。工單：$ticket（已由經理領好，放在 _tickets/doing/）。先完整讀工單、$workdir 的專案規矩（AGENTS.md／CLAUDE.md）、工單列的決策來源與適用的 BDD 契約，再讀它列出的檔案。只做工單允許的範圍。已定的決策直接沿用，不要再問。遇到未定的新業務規則或契約衝突，停下受影響的部分，把證據和問題寫進回執，交經理找人決定。不可自行發明預期結果、改 Then 條款、移除 guard、放寬驗收或降級測試來讓測試通過。刪資料、刪目錄、強推、對外發訊息這類不可逆操作，工單沒寫明就不做，寫進存疑項。不讀取、不輸出任何秘密或憑證檔；需要正式站的驗證留給經理。經理可能已在本機提交先前的工單，你的改動範圍以 git status 與 git diff HEAD 為準，不要改動或重寫既有提交。自檢時起的背景程序，收尾前關掉。跑工單的每條驗收命令。完工後照 $receipt_template 寫回執到工單指定路徑（預設 $workdir/_receipts/<工單名>.receipt.md），用工單的語言；執行引擎一欄寫：pi / deepseek-v4.1-flash（OpenRouter）；完成時間用 TZ=Asia/Taipei date '+%Y-%m-%d %H:%M %z' 取得，只寫進回執給團隊看。每條驗收都貼真實命令和原樣輸出（通過的長輸出照回執模板存檔、貼路徑與尾段），不許編。不要 commit、push、挪工單或動 production。"

# 工人以乾淨環境啟動：不繼承呼叫端（經理 session）已匯出的 token 與業務憑證。
# 只留執行必需的變數；本機磁碟上的 secret 檔仍可讀，隔離的剩餘風險見 SKILL.md。
# 直接 unset 再 exec，不用 env -i：金鑰只在環境變數裡，不出現在任何程序的 argv。
keep=" HOME PATH USER LOGNAME LANG TERM TMPDIR XDG_RUNTIME_DIR DOCKER_HOST HTTPS_PROXY HTTP_PROXY NO_PROXY TZ "
for name in $(compgen -e); do
  [[ $keep == *" $name "* ]] || unset -v "$name" 2>/dev/null || true
done
export USER="${USER:-$(id -un)}" LOGNAME="${LOGNAME:-$(id -un)}" LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}"
export OPENROUTER_API_KEY="$api_key"
unset api_key

# exec 沿用同一個 PID：經理用這行看工人是否還在跑（ps -o etime= -p <pid>）。
# proc_start 讓 wait-worker.sh 分得出這個 pid 後來是不是被別的程序重用了。
read -r proc_stat 2>/dev/null </proc/$$/stat || proc_stat=
read -ra proc_fields <<<"${proc_stat##*) }"
printf 'pi worker start pid=%s ticket=%s%s proc_start=%s at=%s\n' "$$" "$ticket" "${chain:+ session=$session_state}" \
  "${proc_fields[19]:-}" "$(TZ=Asia/Taipei date '+%F %T %z')" >&2
cd "$workdir"
# 工人只做開發：不載入全域／公司 skill（含 Lark）、擴充與 prompt 範本；每一層的 AGENTS.md／CLAUDE.md
# 都不自動載入（上層的 house 規矩寫著怎麼載入團隊秘密）。repo 自己的那份改由上面的指示要求工人用 read 讀。
# 無頭工人不繼承呼叫端的 stdin：開著的 pipe／socket 會讓 CLI 一直等 EOF。
exec "$pi_bin" -p "${session_args[@]}" --no-skills --no-context-files --no-extensions --no-prompt-templates \
  --provider openrouter --model deepseek/deepseek-v4.1-flash --thinking high \
  "$resume_note$prompt" </dev/null
