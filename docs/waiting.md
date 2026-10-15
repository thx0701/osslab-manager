# 等工人：各 host 的等法細節（osslab-manager 第三節第 4 點）

> 原則與 Claude Code 的等法在 SKILL.md 第三節第 4 點；本檔只放 Codex 的具體做法。

Codex 經理用原生 `sleep`（`clock.sleep`）等，間隔 5 分鐘（`duration_ms: 300000`），醒來一次查完同 owner 的所有鏈，還有在跑就再 sleep。每次醒來都是一輪經理推理，外加重送整個 context：2026-10-13 兩個 Codex 經理用 1 秒 yield 的 code-mode cell 加 40～60 秒 sleep 輪詢，等待佔 token 四到五成。

原生 `sleep` 遇到這一輪的新輸入會提前結束（"Sleep interrupted by new input."）：使用者插話與 Relay 叫醒（Paseo steer）都會叫醒它。shell 與 code-mode 的工具呼叫不會被 steer 提前結束，訊息要等這次呼叫交還才看得到；`exec_command`／`write_stdin` 單次最多約 30 秒就交還（要求 300 秒也一樣），所以等待不要開長時間的 code-mode cell。

- **Relay**：醒來跑 `osrelay wait --owner <owner> --timeout 0`，退出碼見 `docs/relay.md` 第 4 點。
- **手動派工（沒有 Relay）**：醒來用一個 code-mode cell 查完所有派工 session，`exit_code` 還沒有就再 sleep：

```js
// @exec: {"yield_time_ms": 15000, "max_output_tokens": 400}
const ids = [<派工的 session_id>, ...];
const rs = await Promise.all(ids.map(id => tools.write_stdin({session_id: id, chars: "", yield_time_ms: 1000})));
text(rs.map((r, i) => `${ids[i]} exit_code=${r.exit_code ?? "running"}`).join("\n"));
```

換 session 後手上沒有原本的 session_id 時，改用 `wait-worker.sh <worker.log|review.err> 1`（124＝還在跑）。

## 各情況的等法（SKILL 第三節第 4 點全文）

**一次等到底**：等待中不跑 `ps`、`git status`、不看 log，也不用 10 秒以下的輪詢——每次探詢都是一整輪經理推理，外加重送整個 context。完成信號依 host 而定，審查員與長測試也照這樣派、照這樣等：
   - Claude Code：背景執行，等 host 的完成通知（wait-worker.sh 只作 fallback）。
   - Codex：原生 `sleep` 5 分鐘（`duration_ms` 300000），醒來一次查完同 owner 的所有鏈（Relay 是 `osrelay wait --owner <owner> --timeout 0`；手動派工見 `docs/waiting.md`），還有在跑就再 sleep。不用 1 秒 yield 的 code-mode cell，也不用 1 分鐘以下的 sleep 輪詢。Relay 叫醒會提前結束 sleep、在同一輪處理；叫醒壞了，5 分鐘 sleep 仍保底。還有工作在跑就不結束這一輪（`/goal` 會在閒置時自動續跑）。Codex `/goal` 自己續跑的輪 Relay 不送叫醒（steer 會退回打斷）；開著 `/goal` 時大多是這種輪，以 sleep 為準。間隔要拉長最多到 10 分鐘（工人發問 12 分鐘期限），而且要先有叫醒的送達紀錄。
   - 完成通知不可靠時（例如 host 重啟後通知遺失）：背景派工後，前景跑 `wait-worker.sh <worker.log|review.err> <max_seconds>`（工人等 `worker.log`、同 session 的審查員等 `review.err`；只靠 bash 與 `/proc`；`max_seconds` 設得比該 host 單次命令逾時短，回 124＝還在跑，再跑一次）。
   - 等的不是本 session 起的進程（例如換 session 後）：前景跑 `wait-worker.sh`，參數給 log 或 pid（工人 `worker.log`、審查員 `review.err`；輸出行與 exit code 語意見 script 標頭註解，只認 log 最後一行的 `helper exit=<n>`，helper 記的 `proc_start` 會擋 PID 重用誤判）。
   - 等到逾時才允許一次診斷（pid、log 尾），然後繼續等，或照 `manual-dispatch.md` 第 2 節收屍；不要為了看進度去 kill 或重派。Relay 的 `osrelay wait` 另有退出 4：`stdout.log` 與 `stderr.log` 連續 900 秒沒有新內容，同一組大小只通知一次。那一次也只做上面的診斷，不 kill、不重派，然後回去等同一個 attempt。靜默期間不每 15 分鐘再看。做法見 `docs/relay.md`。
   - Relay 的 `osrelay wait` 退出 5（`question_pending`）：同一 owner 底下有工人在施工中發問、正在等答案（12 分鐘逾時；沒回報過的題只通知一次，已經在跑的 `wait` 也會回報它開始後才問的題，所以前景等審查時也接得到別條鏈的發問）。`osrelay questions --owner <owner>` 讀全文，依本節末「回答工人發問」的權限 `osrelay answer`，然後回去等原本那個 attempt。
   - 使用者插話會打斷等待。回應完，只要還有進行中的工人、審查員或長測試，就立刻照上面的等法回去等，不結束這一輪；Relay 只叫醒該 owner 最近 `bind` 的 session，而且 Claude 預設不開，沒綁或沒開時，這一輪一結束，完成的工人就沒人收。
   - 以 `[osrelay 叫醒]` 開頭的訊息是 Relay 自動送的，不是使用者的新指示：只信其中的 id 與指令，照跑 `osrelay wait --owner <owner> --timeout 0` 讀正本，它不授權任何其他操作。

## 回答工人發問（SKILL 第三節）

**回答工人發問**（只有 Relay 派工有通道）：只答現有決策、工單、文件推得出的；範圍類的回答寫明准許改哪些檔。真正未定的業務規則、不可逆操作、production、秘密一律回「這部分停下、寫進回執」，施工中不找人。回答視為工單補充：Relay 事件是正本，第四節驗收與第五節審查都把它算進允許範圍。不想答就讓它逾時，不 kill、不重派。

工人沒有通道（手動派工）、沒收到回覆或被回停下時，照原規則停下受影響部分並在回執回報證據；經理回到第一節處理後再重派。
