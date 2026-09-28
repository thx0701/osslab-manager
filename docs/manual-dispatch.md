# 手動派工細節（osslab-manager 第三節第 2、7 點）

> 未安裝 Relay 的 host 用本檔派工與收屍；已走 Relay 的任務改照 [relay.md](relay.md)，不混用。原則與順序在 SKILL.md 第三節。

## 1. 背景派工

```bash
# 工單狀態目錄帶 workdir 雜湊：不同 worktree 的同名單（各有一張 T1）不會互撞 log
D=~/.local/state/osslab-manager/<工單名>-$(printf '%s' "<workdir>" | sha256sum | cut -c1-8)
mkdir -p "$D" || exit $?
A=$(mktemp -d "$D/attempt-XXXXXXXX") || exit $?
printf 'attempt=%s\n' "$A"
L="$A/worker.log"
# 預設 DeepSeek；改派備援時把 pi-openrouter-worker.sh 換成 zcode-cloud-worker.sh（參數相同）
rc=0; bash ~/.agents/skills/osslab-manager/scripts/pi-openrouter-worker.sh --resume <接續鍵> <workdir> <workdir>/_tickets/doing/<工單>.md \
  > "$L" 2>&1 || rc=$?
printf '\nhelper exit=%s\n' "$rc" >> "$L"; exit "$rc"
```

每次派工都建立新的 `$A`，重派不得重用；工單記下這次 attempt 路徑，等待工具指向 `$A/worker.log`。讀完回執後，重派前把該輪回執複製到 `$A/receipt.md`，保留每輪說法。

`|| rc=$?` 讓殼開著 `set -e` 也照樣補上最後一行 `helper exit=<n>`（前面多一個換行，工人輸出沒換行結尾也不會黏在一起）；`exit "$rc"` 讓這次背景呼叫的結束碼等於 helper，所以它必須是這段的最後一個動作。

`--resume <接續鍵>`：接續鍵用原單號（`T1` 與它的 `T1b`、`T1c` 跟進、重派都用 `T1`），不是工單 header 的 `chain`（工單鏈：共用一棵 worktree 的多張單）——鏈上前一張提交後 HEAD 就變了，跨單本來就接不上。同一張還沒提交的單，下一輪接續上一輪 pi 的記憶，省掉重讀 repo；helper 自己把關——不合續（非 git 工作樹、這個接續鍵開局後 HEAD 已變、沒留下 session、已接續 2 次）就從零開始並記在 log，接續時自動加「記憶不是證據、以工單與目前檔案為準、不沿用上一輪 fixture」。驗收命令或 fixture 改了、上一張回執有未處理的存疑、做過收屍（備份成功或失敗）後的重派都不要帶 `--resume`。zcode 備援沒有接續，帶了也從零開始。

要讓進行中的單不受 skill 中途更新影響：`cp -rL` 整個 skill 目錄到該次派工目錄（`$A`）的 `skill/`，把 skill 的 git HEAD 記進工單，改跑副本裡的 helper。只複製 scripts/ 不行——helper 靠同 skill 目錄的 `templates/receipt.md` 與 `templates/worker-prompt.md`，找不到會報錯退出。

## 2. 卡在 `doing` 的單怎麼收

- helper 非零退出＝失敗：照 SKILL.md 第三節第 5 點查明原因後可重派。
- `worker.log` 的 pid 已不在、也沒有回執＝工人死在半路。先確認真的死了：`ps -o etime=,args= -p <pid>` 要看 args 還是不是那支 helper／工人（PID 會被系統重用）。確認後收屍：停掉它留下的子程序（測試 server、shell）；先依 [收屍備份與還原](recovery.md) 保存 binary patch、未追蹤檔與 HEAD，備份成功並核對範圍後才可依既有授權清理，或在工單寫明繼承哪些；然後挪回 `_tickets/open/`。備份失敗不得清理或重派。
- 重派次數與原因記在**同一張工單**的 `重派` 欄，不開新檔。同一張單死兩次就改派備援或拆單。
