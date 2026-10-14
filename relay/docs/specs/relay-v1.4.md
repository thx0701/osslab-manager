# OSSLab Relay v1.4：叫醒經理、owner 等待

覆寫 v1「不自動喚醒經理」：attempt 結束或工人發問時，Relay 透過 Paseo 叫醒該 owner 最近綁定的經理 session。
其餘 v1～v1.3 契約不變：不自動啟動或新建經理 session、不自動重派、不 kill 工人、不改模型。
決策來源：Brain `plans/infra/2026-10-14-osslab-manager-wake-and-tail-mode.md`「定案」一節
（使用者 grill 兩輪「都照你規劃」；Q8 經 GLM-5.3 max 審，推薦 steer＋原生 sleep）。

## 行為

1. `bind <task> --owner O --runtime R --session S [--wake on|off]`：照舊更新 task，另把 owner O 的叫醒對象設為這一筆
   （每個 owner 一個，最後一次 bind 為準）。`--wake` 省略時 codex 為 on、claude 為 off。事件 `manager_bound` 多記 `wake`。
   升級前的綁定不會叫醒，要叫醒就重新 bind。
2. 叫醒事件，只算 owner O 未關閉 task 上的：
   - attempt 進終態（succeeded／failed／interrupted；施工、審查、verify 都算），且還沒被任何 `wait` 回報、也還沒叫醒過；
   - running attempt 上的待答工人發問，且還沒被任何 `wait` 回報、也還沒叫醒過。
   靜默不叫醒；`cancel` 是經理自己的動作，被取消的 attempt 直接記為已回報。
3. runner（`serve`）每秒檢查一次，以 session 為單位：綁到同一 session、叫醒開著的 owner，把各自的叫醒事件合成一則
   （每個 owner 一段、各附一條指令），交給 helper 送出。條件：沒有送到一半的叫醒、距上次送出至少 60 秒、距上次失敗
   至少 300 秒。成功後這些事件記為已叫醒，每個相關 task 記 `wake_sent`，該 session 的失敗紀錄清掉；失敗記在綁定上，
   事件保持未叫醒但不單獨重送，等有新的叫醒事件時一起併入。同一 owner、同一失敗原因連續發生只在 task 上記一次
   `wake_failed`。runner 停止時不再送新的，送到一半的等 helper 結束（上限 90 秒）。
4. 叫醒訊息是固定模板：以 `[osrelay 叫醒]` 開頭（不得以 `/` 開頭，否則 Paseo 當成斜線指令而改成打斷），
   只放 owner、task／attempt id、種類、狀態、最早期限的時分與要跑的指令 `osrelay wait --owner <O> --timeout 0`；
   不放回執、log、工人寫的 where／options 等任何文字。owner 的控制字元換成空白。
5. helper `osrelay/paseo-wake.mjs`（Node，Paseo 本身的執行環境）用 Paseo CLI 套件內的 client 連本機 daemon：
   - `check`：連得上就回 `{"ok": true}`；
   - `send <agent>`（訊息從 stdin）：agent 不存在回 `agent_not_found`、已封存回 `agent_archived`、正在跑 Paseo 沒開的輪
     （`activeTurn.turnId` 以 `autonomous-` 開頭，例如 Codex `/goal` 的續跑）回 `agent_autonomous_turn`，都不送；
     否則 `sendAgentMessage(..., {activeTurnBehavior: "steer"})`：經理正在跑就塞進同一輪（會提前結束 Codex 原生
     `sleep`，不打斷 shell 指令），閒置就開新一輪。
   helper 以 Relay 的乾淨環境變數啟動，90 秒逾時。`OSRELAY_WAKE_HELPER=off` 關閉叫醒，給可執行檔路徑則改用它
   （測試替身）；不設時用 PATH 上的 `node` 跑內建 helper。`OSRELAY_PASEO_CLI` 可指定 Paseo CLI 套件目錄，
   預設由 PATH 上 `paseo` 的實際路徑推出。
6. `wait --owner O [--timeout T] [--silence S]`（與 `wait <attempt>` 二選一）一次看 owner O 所有 attempt：
   - 已結束但還沒被回報的 attempt（含這次 wait 開始前就結束的）；
   - 待答發問：沒被回報過的，以及這次 wait 開始後才出現的（同 v1.3）；
   - 靜默：running attempt 的 stdout／stderr 連續 S 秒沒變，同一組大小只報一次（同 `wait <attempt>`）；
   - 叫醒失敗：綁定上尚未回報的失敗。
   有前三類任一就返回，回報的項目記為已回報。退出碼：有發問 5（`question_pending`），否則有結束的 attempt 0，
   否則有靜默 4（`wait_silent`）；owner 沒有進行中的 attempt 也沒有可回報的 0（`idle: true`）；
   逾時 3（`wait_timeout`）。每種返回都附 `attempts`、`questions`、`silent`、`wake`、`running` 五欄。
   `--timeout 0` 查一次就走。`wait <attempt>` 回報終態時也把該 attempt 記為已回報。
7. `doctor` 多 `wake`：helper 是否啟用、`check` 結果、各 owner 的綁定與最近一次叫醒結果。
   `context` 的 `manager_contract` 改寫為會叫醒、叫醒訊息只信其中的 id 與指令。

## Schema

`user_version` 4：attempts 加 `reported`、`woken`，questions 加 `woken`，新增 `bindings`（主鍵 owner，含叫醒節奏、
最近失敗與失敗那批事件）。
v1～v3 檔開機自動升級；升級時已在終態的 attempt 全部記為已回報、已叫醒，不會補叫歷史。
v1.3 程式看到 version 4 會拒絕啟動；要回退就留在升級前的 release，不要把舊程式指到已升級的 state。

## 已知限制

- helper 依賴 Paseo CLI 套件內部的 `dist/utils/client.js`／`daemon-target.js`（CLI `send` 與 MCP `send_agent_prompt`
  都沒開放 steer）。Paseo 升級改了它們時 `doctor` 的 `check` 會失敗、叫醒退化為失敗紀錄；經理仍有 5 分鐘 sleep 保底。
- steer 被 provider 拒絕而 turn 還在時，Paseo 會退回打斷（`agent-manager` 的 replace 分支）。已知兩個成因都先擋：
  模板不以 `/` 開頭；autonomous 輪不送（2026-10-14 實測 Codex `/goal` 續跑中送 steer 會中止該輪）。所以經理開著 `/goal`
  時叫醒幾乎都送不出去（記 `agent_autonomous_turn`、5 分鐘後再試），由經理的 5 分鐘 sleep 保底。從查詢到送出之間
  若剛好換成 autonomous 輪，仍可能被打斷。判斷依賴 Paseo 的 turn id 命名。
- steer 要等目前這次工具呼叫交還才進入對話：Codex shell／code-mode 約 30 秒一交還；原生 `sleep` 立即結束。
- bind 的 session 不是 Paseo agent id（例如不在 Paseo 的 runtime session）時，叫醒必失敗，只記一筆。
- 回報是「先標記、後輸出」（at-most-once，v1.3 的發問已是如此）：wait 程序在標記後、印出前死掉，那批結束不會再被回報，
  也不會再叫醒。只有經理該跑 `wait`／`wait --owner`。
- 叫醒模板裡只有 owner 是經理自訂的自由文字（只換掉控制字元）；工人寫的文字進不來。
- 一則通知超過 3500 字（多個 owner 或很長的名稱）改送只有數量的精簡版，經理用 `osrelay list` 找 owner。
- `doctor` 的 `wake.check` 用呼叫端的環境執行，不等於 runner（systemd）的環境；runner 那邊送不出去會記在 bindings，
  由 `doctor` 的 `wake.bindings` 與 `wait --owner` 的 `wake` 看到。
- v1／v2 檔與另一個程序同時開檔升級時，舊的前置腳本仍可能把 user_version 寫回 2／3（既有寫法）；現役 state 已是 v3，不會走到。

## Testing

Regression：`make test` 以假 helper（測試寫出的可執行檔）覆蓋：attempt 結束與工人發問各叫醒一次、合併成一則、
同一 session 的多個 owner 共用一則與間隔、60 秒間隔、失敗後 300 秒退避且同一批事件不單獨重送、已被 wait 回報的不送、claude 預設不叫醒、`--wake off`、最後一次 bind 為準、
封存或不存在不重複記、訊息不含工人文字且不以 `/` 開頭、`OSRELAY_WAKE_HELPER=off` 完全不送；
`wait --owner` 的五種返回、開始前結束的 attempt、跨 task 合併、靜默只報一次、叫醒失敗只報一次、owner 隔離；
v3 升級（歷史 attempt 不補叫）與 v5 拒絕。
Business acceptance：真 Paseo Codex agent 綁定拋棄式 fixture task，fixture 工人結束時 steer 結束其原生 sleep；
另測舊 1 小時 code-mode cell 期間的延遲、連續多次叫醒、`/goal` 中叫醒、helper 在 systemd 乾淨環境連 daemon。
helper 的判斷另以 node 跑 `tests/fixtures/fake-paseo-cli` 測：steer 旗標、閒置／前景輪送出、autonomous／封存／不存在不送、`/` 開頭拒絕。
