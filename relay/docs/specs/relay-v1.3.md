# OSSLab Relay v1.3：工人施工中發問

新增 pi 工人與經理之間的問答通道。其餘 v1／v1.2 契約不變：不自動喚醒經理、不自動重派、不 kill 工人。
決策來源：Brain `plans/infra/2026-10-10-osslab-manager-worker-ask-spec.md`（使用者 grilling Q1–Q12 定案、GLM-5.3 High 審查）。

## 行為

1. Relay 起 pi 施工 attempt 的 helper 時，環境多三個變數：`OSRELAY_ATTEMPT`（attempt id）、`OSRELAY_STATE`（state 目錄）、
   `OSRELAY_BIN`（啟動它的這一版 `bin/osrelay`）。glm 工人、review、verify 都不給。helper 與工人驅動程式負責不把它們傳給 pi。
2. 工人驅動程式用內部子指令（不列在說明，經理不用）：
   - `_ask post <attempt> --qid Q --timeout-ms N --payload '<JSON>'`：payload 固定 `kind`（`scope_conflict`｜`contract_conflict`｜
     `ambiguous_ticket`）、`where`、`options`（2–3 個）、`recommendation`、`impact`；格式不符回 `invalid_question`。
     `qid` 限 `[A-Za-z0-9_.:-]{1,128}`，`N` 限 1..3600000。只接受 running 的 worker attempt，否則 `attempt_not_running`。
     deadline＝post 當下＋N。同 qid 同 payload 重送回同一題；payload 不同回 `idempotency_conflict`。
   - `_ask poll <attempt> --qid Q` → `{qid, state, answer, …}`，state 為 `pending`｜`answered`｜`expired`｜`withdrawn`。
     pending 已過 deadline 先記成 expired 再回。
   - `_ask expire <attempt> --qid Q`：工人那邊已逾時。pending 改 expired；已 answered 不變、不報錯；冪等。
3. 經理：
   - `wait <attempt>` 發現**同 owner** 任一 running attempt 有尚未通知過的待答題目，就以退出碼 5 返回，
     `error.code=question_pending`，`error.message` 含 attempt、qid、kind、where 摘要與 deadline，`error.details.questions` 附全文。
     先於終態與逾時判斷。每一題只通知一次：不答、讓它逾時的話，之後的 `wait` 不會為它再返回 5。例外是已經在跑的 `wait`：它開始之後才出現的題目，就算已被別的 `wait`（例如背景等待）回報過，它也要返回 5。Claude 經理卡在一個前景 `wait` 時讀不到背景 `wait` 的退出碼，2026-10-11 實際因此兩題拖到接近 12 分鐘期限。
   - `questions [--owner X]` 列 running attempt 上的待答題目全文。
   - `answer <attempt> --qid Q --owner X --text …`：owner 不符回 `owner_mismatch`；題目已答、已過 deadline、或 attempt 已結束
     回 `question_expired`（過期或結束的原因同時記下來）。回答視為工單補充，事件為正本。
4. attempt 進終態時（runner 的 reconcile），仍 pending 的題目改 `withdrawn`。
5. `status`／`context` 的 `questions` 列出本 task 每一題與答案；事件有 `question_asked`、`question_answered`、
   `question_expired`（`by: deadline|worker`）、`question_withdrawn`。

## Schema

`user_version` 3：新增 `questions` 表（主鍵 attempt_id＋qid）。v1、v2 檔開機自動升級。v1.2 程式看到 version 3 會拒絕啟動；
要回退就留在升級前的 release，不要把舊程式指到已升級的 state。

## Testing

Regression：`make test` 以 fixture helper 模擬驅動程式的 post／poll，覆蓋：退出 5 只通知一次、答案送達工人、同 owner 跨 attempt
通知且不跨 owner、逾時後拒答、attempt 結束撤回、子指令格式與冪等、只有 pi 施工單拿到環境變數、v2 升級與 v4 拒絕。
