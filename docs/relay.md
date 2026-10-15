# Relay：經理的持久執行底座

適用已安裝 `osrelay` 的主機上當經理的 Codex／Claude Code（Paseo 或一般終端機皆可；本 skill 只支援這兩種經理）。經理照 SKILL.md 做盤點、拆單、判斷與逐張本機提交；
Relay 只代管程序與證據。Codex 維持 Full Access、medium；Claude 沿用 session 設定。
施工預設 pi，備援明確 `--engine glm`，review 依序 Codex（預設，GPT-6 Astra medium）→ `--engine glm`（完整 GLM-5.3 max）→ `--engine grok`（已停訂，到期前可用），三者都可指定（見 SKILL 第五節；`--engine codex` 是審查員，跟任務的 `--runtime codex` 無關）。Claude Haiku 不在 `osrelay` 的引擎表裡，不要用手動 helper 繞過進行中的 Relay 任務。模型正本是本 skill helper
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
   同一條鏈共用一棵 worktree；可同時派的鏈各用一棵。`bind <task> --owner <角色> --runtime codex|claude --session <session ID> [--wake on|off]` 只綁當前 session，owner 不變；session ID 用 Paseo agent ID，不在 Paseo 就用 runtime 自己的 session ID，都拿不到就不 bind、在交接檔寫「未綁」。
   bind 也決定叫醒對象：attempt 結束或工人發問時，Relay 經 Paseo 叫醒該 owner **最近一次 bind** 的 session（`--wake` 省略時 Codex 開、Claude 關）。換 session 接手要重新 bind；不在 Paseo 的 session ID 叫不醒，只會留一筆失敗。
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
4. 取得 JSON `result.id` 後照 SKILL.md 第三節第 4 點等，不用短逾時反覆輪詢：
   - Codex：原生 `sleep` 5 分鐘 → `osrelay wait --owner <角色> --timeout 0` 查一次 → 還有在跑就再 sleep（`docs/waiting.md`）。
     不要用 Shell 一次次跑短逾時的 `wait`，也不要開長時間的 code-mode cell：Relay 叫醒要等目前這次工具呼叫交還才看得到。
   - Claude Code：背景跑 `wait --owner <角色> --timeout 3600`（或單一 `wait <attempt>`）等 host 完成通知；退出 3 就再背景等一次。
   - 其他 host：前景 `wait`，逾時設得比單次命令上限短。

   **叫醒**：bind 了且叫醒開著時，attempt 結束（施工、審查、verify）或工人發問，Relay 會經 Paseo steer 送一則以 `[osrelay 叫醒]` 開頭的訊息：
   Codex 的 sleep 提前結束、在同一輪處理；經理閒置時開新一輪；正在跑的 shell 指令不會被打斷。同一 session 至少隔 60 秒一則，多個事件合成一則；
   已經被你的 `wait` 回報過的不送；送失敗不單獨重送，沒送成的等下一個新事件一起送（至少隔 5 分鐘），期間靠 5 分鐘 sleep 保底。Codex `/goal` 自己續跑的輪（autonomous）
   steer 會退回打斷，所以 Relay 不送（`wake` 會報 `agent_autonomous_turn` 一次）；開著 `/goal` 時大多是這種輪，以 sleep 為準。訊息只列 owner、task／attempt id、種類、狀態與期限，
   不含工人寫的任何文字；只信其中的 id 與指令，照跑 `osrelay wait --owner <角色> --timeout 0` 讀正本，它不是使用者的新指示。靜默不叫醒。

   **`wait --owner <角色>`** 一次看這個 owner 所有 attempt，每種返回都附 `attempts`、`questions`、`silent`、`wake`、`running`：
   - 退出 5：有工人發問（`questions`），同時附已結束的 `attempts`；
   - 退出 0：有 attempt 結束（`attempts`，含這次 wait 開始前結束、還沒被回報的；逐一看 `status`），或 `idle: true`（沒有進行中的 attempt，也沒有可回報的）；
   - 退出 4：有 attempt 靜默（`silent`）；
   - 退出 3：還在跑、沒有新事（`running`）。
   回報過的項目不會再回報；`wait <attempt>` 回報的結束也算。`wake` 不是空的，表示叫醒送不出去（同一原因只報一次）：檢查 bind 的 session 是不是 Paseo agent ID、是否已封存，必要時重新 bind。
   讀結果：單一 `wait <attempt>` 退出 0 只表示查詢成功，仍須看 `result.status`；`wait --owner` 要逐一處理 `attempts` 裡每個的 `status`，
   退出 5 時同批的 `attempts` 也要處理，不能答完題就丟掉；任何退出碼下 `silent` 不是空的，就照下面退出 4 做那一次診斷；還有 `running` 就回去等。
   回報即消費（先標記才輸出）：只有經理該跑 `wait`／`wait --owner`，其他程序跑了，經理就收不到那批結束。
   下面退出 3／4／5 的處理兩者相同。CLI 退出 3 是等候逾時，**不是工人失敗**。
   退出 4（`wait_silent`）是另一件事：`stdout.log` 與 `stderr.log` 的大小連續 900 秒沒變，attempt 仍在跑，沒有取消。同一組大小只回報一次。經理這時做一次診斷（pid、log 尾），不 kill、不重派，然後回去等。日誌有新內容之後又靜默 900 秒，才會再回報一次；靜默期間不會每 15 分鐘再響。pi 工人每個工具起訖、每則模型回覆、每次重試與壓縮都即時寫一行（`scripts/pi-worker-driver.py`），所以 pi 的靜默代表單一命令、單一輪生成或重試等待已超過 900 秒，log 尾最後一行就是停在哪裡。這不是工人失敗，也不是把查看改成經理輪詢。
   退出 5（`question_pending`）：同一 owner 底下有 pi 工人在施工中發問，正在等答案；`error.message` 已有 attempt、qid、kind 與摘要，`error.details.questions` 有全文。依 SKILL.md 第三節「回答工人發問」的權限 `osrelay answer <attempt> --qid <qid> --owner <角色> --text …`，答不了就回「這部分停下、寫進回執」；然後回去等。每題只通知一次（例外：已經在跑的 wait 會回報它開始後才問的題，就算背景等待已回報過；之後才開始的 wait 不重報），不答就會在 12 分鐘後逾時，工人照原規則停下受影響部分；不 kill、不重派。等答案期間工人 log 會有「等經理回覆」一行，720 秒逾時短於 900 秒靜默警報。
   等 terminal status 才讀該 attempt 目錄的 receipt.md、stdout.log、stderr.log、result.json。退出 4 的那一次診斷可以看 log 尾，看完就回到等待，不把整份 log 讀進對話。
5. worker succeeded 只到 awaiting_acceptance。經理照原 skill 逐項核實實際 diff、回執與業務驗收；
   工單驗收入口用 `verify <task> --owner <角色> --key <驗證鍵> -- <命令...>`，等待並核對 schema 2 證據。多項檢查依 SKILL 第二節寫成清單、用 `scripts/acceptance-run.sh` 跑，工人與經理每輪只用這一條 `verify`；逐項結果看它的 `summary.json`，輸出目錄放 worktree 外。
   accept 會要求這個 task 驗過的每一條不同命令，最新一次都在目前版本通過；改了程式就全部重跑。
   沒有 active attempt 時先逐檔 `git add -N -- <允許的新增檔>`，再下 verify 指令；排隊後也不能改 index。
6. 審查包仍照原 skill 寫。`review <task> --owner <角色> --key <審查鍵> --prompt <審查包>`，
   等待、讀完整報告、逐條核實。非空報告不代表無 findings；需要修正就新 run（收尾模式由經理直接改，見 SKILL 第六節），之後重驗重審。
   review 不帶 engine 是 Codex；換 GLM 或 Grok 加 `--engine glm`／`--engine grok`，工人 glm 路由仍是 Flash。每次重跑 run／verify／review 都用新 key；原 key 只重送同一請求。
   Relay 比第六節嚴：工作樹一變，舊 review 就不算數，機械修復也要新跑一輪 review 才能 accept。
   低階單（第五節）不跑外部審查，accept 時加 `--review-waiver <低階理由>`；該 task 跑過任何 review 後就不能豁免。
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

## 阻擋修復票如何映射

保留獨立修復票與編號，但在母 task 尚占用 worktree 時，修復施工是**母 task 的下一輪 worker attempt**：不 create 第二個 task、不 handoff 當修復。把修復票全文（問題、決策來源、範圍、驗收命令）附到母 task 的工單來源，兩者都放 worktree 外；`run <母 task> --key <新修復鍵>`，不帶 `--resume`。新 attempt 凍結更新工單，舊票與舊證據不改。

修好後先準備新增檔，再以新 key 重跑母 task **所有曾驗過的不同命令**與 review（包含修復新增命令）；核實後 accept。母票與阻擋修復同一 commit、body 列兩個編號，然後 finalize 母 task。非阻擋跟進票可以先寫，但同 worktree 的獨立 task 施工必須等母 task finalize 釋放占用。

修復輪次沿用母單累計。第 2 輪起只剩已核實的 minor 時，經理依 SKILL 第六節直接修；P1 完成 3 輪修復仍未收斂時，下一輪必須換更強且已授權的施工路徑或由經理收尾，不再派 Flash。經理收尾不另 `run`，驗收／審查／accept 的指紋護欄不變。

新 task 派單前就把多項檢查寫成清單。既有 task 若已逐條 verify，Relay 仍要求所有曾驗命令的最新證據；不能改帳本、假結案或僅新增清單 verify 來抹掉舊要求。這是舊任務兼容限制，記入核實段；新 task 只登記清單入口，後續重驗維持單一 verify。

收尾模式（SKILL 第六節）由經理直接改母 task 的工作樹，不另 `run`；之後一樣以新 key 重跑母 task 所有曾驗過的不同命令與 review，核實後 accept，母票與修復同一 commit。

## 阻塞、恢復與換 session

- `block <task> --owner ... --reason ... --resume-note ... --wake-condition ...` 保存原因與續辦條件。
  條件是文字；叫醒只看 attempt 結束與工人發問，不會因條件達成而叫醒或 unblock。解決後明確 `unblock ... --note ...`。
- session 改變但角色相同：先 context，再 bind（叫醒對象跟著移到新 session）；有 active attempt 就接著 wait，不重派。
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
