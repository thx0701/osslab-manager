# Relay：經理的持久執行底座

適用已安裝 `osrelay` 的主機上當經理的 Codex／Claude Code（Paseo 或一般終端機皆可；ZCode／Cursor 可派工，但 `bind` 只接受 codex／claude）。經理照 SKILL.md 做盤點、拆單、判斷與逐張本機提交；
Relay 只代管程序與證據。Codex 維持 Full Access、medium；Claude 沿用 session 設定。
施工預設 pi，備援明確 `--engine glm`，日常 review 仍走 Grok helper；模型正本是本 skill helper
（`osrelay doctor` 的 routes 會列出實際值），每個 attempt 凍結整份 skill。

先 `osrelay doctor`、`osrelay list`。查既有任務的 `context <task> --runtime codex|claude`，
讀取 owner、parent、attempts、events、回執與 next_step，不靠前一段記憶。最大項用同一個
`context <goal id>`，讀每節狀態與證據指紋。`runner.alive=false`
表示先處理 runner；不要繞過 Relay 手動派同一 worktree。程式在公開 repo 的 [`relay/`](https://github.com/thx0701/osslab-manager/tree/main/relay)，
部署與 Paseo 操作見其中的 `docs/paseo.md`。

## 工單到驗收

1. 沿用本 skill 工單模板與依賴判斷。原工單留在原路徑，不用搬 open/doing/done 控制狀態。
   工單、審查提示、審查報告副本與核實筆記放 worktree 外（或 repo 已 ignore 的目錄）：未追蹤檔會算進指紋，
   `create`／`review` 以 `inside_worktree` 拒絕，事後才寫進去則讓 accept 回 `stale_evidence`。
   同一 worktree、同一任務只用一份 state，預設 `~/.local/state/osslab-relay`。
2. 規格段先 `osrelay goal create --id <最大項> --owner <角色> --note <確認清單>`。
   每張工單 `osrelay create --id <全域唯一任務名> --workdir <Git工作樹> --ticket <工單> --owner <穩定角色> --goal <最大項> --chain <鏈名>`。
   同一條鏈共用一棵 worktree；可同時派的鏈各用一棵。`bind <task> --owner <角色> --runtime codex|claude --session <session ID>` 只綁當前 session，owner 不變；session ID 用 Paseo agent ID，不在 Paseo 就用 runtime 自己的 session ID，都拿不到就不 bind、在交接檔寫「未綁」。
   驗收段用 `context <最大項> --runtime codex|claude` 看每節的 state、回執路徑、verify 與 review 指紋，不靠交接檔拼這棵樹。
3. `run <task> --owner <角色> --key <本輪請求鍵>`。同一請求重送沿用 key；改了要求／重新派工用新 key。
   重送時連 --note 都保持逐字一致；變更請求用新 key。
   依 skill 判斷要換 GLM 時，加 `--engine glm --note <改派原因>`，不自動 fallback。
   每次沒帶 `--resume` 的 pi 工人都從零開始，並以自己的 attempt id 開一個 pi session。同一張單要接續記憶時加 `--resume`：
   接續這張單最新成功 pi 工人的 session，與 `--chain`（工單鏈）無關，不用給名字。
   Relay 在排隊前拒絕，不改成悄悄 fresh：不是 pi、做過 recover、還沒有成功工人、同一 session 已接續 2 次、工單與開 session 那輪凍結的不同、HEAD 與開 session 時不同、上一份成功回執的「風險與存疑」不是「無」、或 pi session 檔不在。
   通過後 helper 帶 `--require-resume`，它自己的門檻不過就失敗（helper exit 3），也不改成從零開始；此時工作樹沒動，
   attempt 記 failed（`resume_refused`），task 回到排隊前狀態，不必 recover，也不算接續次數。這和 `osrelay wait` 的退出 3（等候逾時）是兩回事。
   拒絕後用新 key 決定重派或改從零；不要用同一個 key 拿掉 `--resume` 假裝原請求還在。記憶不是證據。
4. 取得 JSON `result.id` 後一次等到底，不用短逾時反覆輪詢：Claude Code 背景跑 `wait <attempt> --timeout 3600`
   等完成通知；其他 host 前景 `wait`，逾時設得比單次命令上限短。
   Codex 不要用 Shell 一次次跑 `osrelay wait --timeout 25`（每次都是一輪推理）；用 code-mode 跑下面這個 cell，
   `@exec` 那行不能省，一次呼叫等到 attempt 結束（2026-09-29 實測 Codex 0.157.1：一次呼叫等完 70 秒）：

   ```js
   // @exec: {"yield_time_ms": 3600000, "max_output_tokens": 800}
   let r = await tools.exec_command({cmd: "osrelay wait <attempt> --timeout 3300", yield_time_ms: 30000});
   while (r.exit_code === undefined || r.exit_code === null) {
     r = await tools.write_stdin({session_id: r.session_id, chars: "", yield_time_ms: 30000});
   }
   let out = r.output ?? "", brief = out.slice(-400);
   try { const j = JSON.parse(out.slice(out.indexOf("{"))), a = j.result ?? {};
         brief = JSON.stringify({ok: j.ok, status: a.status, exit_code: a.exit_code, error: a.error ?? j.error, directory: a.directory}); } catch (e) {}
   text("exit_code=" + r.exit_code + "\n" + brief);
   ```

   退出 3（仍在跑）就再跑同一個 cell。使用者插話打斷時，回應完立刻回去等同一個 attempt（SKILL.md 第三節第 4 點）。
   CLI 退出 3 是等候逾時，**不是工人失敗**；退出 0 只表示查詢成功，仍須看 `result.status`。
   等 terminal status 才讀該 attempt 目錄的 receipt.md、stdout.log、stderr.log、result.json。
5. worker succeeded 只到 awaiting_acceptance。經理照原 skill 逐項核實實際 diff、回執與業務驗收；
   工單每條驗收命令各跑一次 `verify <task> --owner <角色> --key <驗證鍵> -- <命令...>`，等待並核對 schema 2 證據。
   accept 會要求這個 task 驗過的每一條不同命令，最新一次都在目前版本通過；改了程式就全部重跑。
6. 審查包仍照原 skill 寫。`review <task> --owner <角色> --key <審查鍵> --prompt <審查包>`，
   等待、讀完整報告、逐條核實。非空報告不代表無 findings；需要修正就新 run，之後重驗重審。
   Relay 比第六節嚴：工作樹一變，舊 review 就不算數，機械修復也要新跑一輪 review 才能 accept。
   低階單（第五節）不跑 Grok，accept 時加 `--review-waiver <低階理由>`；該 task 跑過任何 review 後就不能豁免。
7. 已核實才 `accept <task> --owner <角色> --note <核實結論>`。Relay 檢查每條 verify 與最新 review（或豁免）成功、
   對應目前 Git 指紋且證據未被置換；不代替人判斷 oracle。成功後是 `accepted`，仍保留 worktree 占用。
8. 照原 skill 逐張本機 commit，再 `finalize <task> --owner <角色> --commit <SHA> --note <提交核實>`。
   Relay 核對 SHA 是目前 HEAD、工作樹與暫存區乾淨、提交內容等於 accept 保存的 tree，
   且為驗收起點的直接單親子提交，才轉 `done` 並釋放占用。沒有變更可用原 HEAD；同 SHA 重送冪等。
   Relay 不代 commit。`accepted` 不能再 run／verify／review／block／handoff；可 bind 接手後 finalize，
   或明確 abandon。不以改 DB 或假結案放鎖。

沒帶 `--resume` 的工人從零開始。凍結工單附上本輪唯一 receipt 路徑；以該路徑為準，
不沿用模板預設回執位置。經理不要在 attempt 運行期間改工單來源以外的受驗工作樹。
不同鏈且不同 worktree 時，一條鏈的 review 可以跟另一條鏈的 `run` 同時進行。同一 worktree 的工人、verify、review 仍不交錯寫。

## 阻塞、恢復與換 session

- `block <task> --owner ... --reason ... --resume-note ... --wake-condition ...` 保存原因與續辦條件。
  條件是文字，不會自動喚醒。解決後明確 `unblock ... --note ...`。
- session 改變但角色相同：先 context，再 bind；有 active attempt 就接著 wait，不重派。
- 角色交接：`handoff <task> --owner <舊角色> --to <新角色> --key <交接鍵> --note <交接內容>`。
  同一交易關閉舊任務、建立有 parent 的新任務並轉移 worktree 占用；新 session 由人／既有 host 開啟。
- recovery_required：讀完半成品與錯誤，確認接受繼承後 `recover <task> --owner ... --note <繼承範圍>`。
  先跑既有 backup helper，成功才恢復 ready；live process／OS lock 或備份失敗會拒絕。
  不自動 reset/clean/kill；其他清理仍依原 skill 的授權與備份規矩。
- queued 未啟動可 `cancel <attempt> --owner ... --note ...`；不提供無條件殺掉執行中的工人。

指紋範圍沿用 evidence-run：ignored 檔、submodule 內部及外部服務須另外驗收。
同一使用者能存取 DB 和 repo，owner／鎖是協作契約，不是惡意程式隔離。

handoff 後繼需重新 verify／review。cancel／block 不釋放 worktree 占用；確定不做用
`abandon <task> --owner ... --note <原因>`（無進行中 attempt、非 recovery_required），不動工作樹、保留證據。
廢棄／卡住程序的處理與大工作樹限制見 Relay 的 `docs/paseo.md`（公開 repo 在 `relay/docs/paseo.md`），不假 accept 或直接改 DB。
