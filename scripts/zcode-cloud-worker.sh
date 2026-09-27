#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s <workdir> <ticket-path>\n' "$0" >&2
  exit 2
fi

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

prompt="你是這張工單的執行者，無頭運行，沒有人能回答你的問題。工單：$ticket（已由經理領好，放在 _tickets/doing/）。先完整讀工單、$workdir 的專案規矩（AGENTS.md／CLAUDE.md）、工單列的決策來源與適用的 BDD 契約，再讀它列出的檔案。只做工單允許的範圍。已定的決策直接沿用，不要再問。遇到未定的新業務規則或契約衝突，停下受影響的部分，把證據和問題寫進回執，交經理找人決定。不可自行發明預期結果、改 Then 條款、移除 guard、放寬驗收或降級測試來讓測試通過。刪資料、刪目錄、強推、對外發訊息這類不可逆操作，工單沒寫明就不做，寫進存疑項。不讀取、不輸出任何秘密或憑證檔；需要正式站的驗證留給經理。經理可能已在本機提交先前的工單，你的改動範圍以 git status 與 git diff HEAD 為準，不要改動或重寫既有提交。自檢時起的背景程序，收尾前關掉。跑工單的每條驗收命令。完工後照 $receipt_template 寫回執到工單指定路徑（預設 $workdir/_receipts/<工單名>.receipt.md），用工單的語言；執行引擎一欄寫：zcode / GLM-5.3-Flash；完成時間用 date 命令取得，不要估。每條驗收都貼真實命令和原樣輸出，不許編。不要 commit、push、挪工單或動 production。"

# 工人以乾淨環境啟動：不繼承呼叫端（經理 session）已匯出的 token 與業務憑證。
# 只留執行必需的變數；本機磁碟上的 secret 檔仍可讀，隔離的剩餘風險見 SKILL.md。
# 直接 unset 再 exec，不用 env -i：金鑰只在環境變數裡，不出現在任何程序的 argv。
keep=" HOME PATH USER LOGNAME LANG TERM TMPDIR XDG_RUNTIME_DIR DOCKER_HOST HTTPS_PROXY HTTP_PROXY NO_PROXY "
for name in $(compgen -e); do
  [[ $keep == *" $name "* ]] || unset -v "$name" 2>/dev/null || true
done
export USER="${USER:-$(id -un)}" LOGNAME="${LOGNAME:-$(id -un)}" LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}"
export TZ=Asia/Taipei
export ANTHROPIC_API_KEY="$api_key"
unset api_key
export ZCODE_MODEL=GLM-5.3-Flash ZCODE_BASE_URL=https://open.bigmodel.cn/api/anthropic

# exec 沿用同一個 PID：經理用這行看工人是否還在跑（ps -o etime= -p <pid>）。
printf 'zcode worker start pid=%s ticket=%s at=%s\n' "$$" "$ticket" "$(date '+%F %T %z')" >&2
# 無頭工人不繼承呼叫端的 stdin：開著的 pipe／socket 會讓 CLI 一直等 EOF。
exec node "$zcode_bin" --prompt "$prompt" --cwd "$workdir" --mode yolo --no-color </dev/null
