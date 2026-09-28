# OSSLab Relay v1.2：最大項、鏈、有條件接續

覆寫 v1「固定從零啟動 worker」那一條。其餘 v1 契約不變：不自動喚醒、不自動重派、同一 worktree 不交錯寫、accept 仍逐條對指紋。

## 行為

1. `goal create --id --owner --note` 建立最大項。相同 id、owner、note 重送回同一筆；任一不同，或 id 已被 task 用過，回 `id_conflict`。
2. `create --goal <id> --chain <鏈名>` 把工單掛上最大項。有 goal 就必須有 chain。goal 不存在回 `not_found`。handoff 後繼複製 goal_id 與 chain。沒有 goal 的舊用法仍可建 task。
3. `context <goal-id> --runtime codex|claude` 列出每個 child 的 state、chain、workdir、最新成功工人回執路徑與 sha256、每條 verify 命令的最新證據、最新未取消 review 的證據。這是索引，不代替經理判斷。
4. 同一 worktree 仍只能有一個占用。不同 worktree 的鏈可以一邊 build、一邊 review。
5. 接續鍵屬於這張 task，不是 chain：每次沒帶 `--resume` 的 pi 工人都以自己的 attempt id 開一個具名 session
   （helper 收到 `--resume <attempt id>`，session 不存在就新開）。chain 只表示共用 worktree 的工單鏈；
   鏈上前一張提交後 HEAD 已變，舊 session 本來就不能接續。
6. `run --resume` 只給 pi，接續這張 task 最新成功 pi 工人的 session。排隊前拒絕（`resume_refused`），不悄悄改成 fresh：
   - 引擎是 glm、這張 task 做過 recover
   - 還沒有成功的工人，或最新成功工人沒有 session（glm 或 v1.2 以前的 attempt）
   - 同一 session 已啟動的 resume 已達 2 次（canceled 的不算）
   - 工單檔與開 session 那一輪的 `ticket.original.md` 不同
   - HEAD 與開 session 那一輪的 before head 不同（工作樹髒可以）
   - 最新成功回執的「## 4. 風險與存疑」有內容且不是「無」；沒有這一節不算存疑；回執檔不見算存疑
   - `~/.local/state/osslab-manager/pi-sessions/<session>-<workdir sha256 前 12 碼>/` 沒有 `*_<session>.jsonl`
7. 通過時 helper 收到 `--resume <session> --require-resume`：helper 自己的門檻（HEAD、次數、session 檔）不過就以
   exit 3 失敗，不改成從零開始。exit 3 且工作樹未變時，attempt 記 failed（`resume_refused`），task 回到排隊前狀態，不進 recovery_required，也不算入 2 次上限；工作樹有變仍照一般工人失敗處理。凍結工單寫明接續的 session 與「記憶不是證據」。同一 key 重送仍回原 attempt，即使之後已達上限。

## Schema

`user_version` 2。v1 檔開機會加 `goals`、`tasks.goal_id`、`tasks.chain`。v1 程式看到 version 2 會拒絕啟動；要回退就留在升級前的 release，不要把 v1 程式指到已升級的 state。

## Testing

Regression：`make test` 覆蓋 goal context、handoff 複製鏈、resume 各拒絕條件與 2 次上限、同鏈不同 task 不共用 session、v1 升級後舊 task 還在；另以真實 helper 快照配假 pi 驗「開 session → 接續」。測試一律用暫存 HOME，不呼叫付費模型。
