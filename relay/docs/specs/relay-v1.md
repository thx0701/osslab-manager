# OSSLab Relay 首版契約

## Problem Statement

OSSLab manager 的經理目前手動保管 pid、log、attempt、回執與交接。Paseo session 中斷後，需要重新推理進程與工單狀態，可能重複派工或失去執行結果。

## Solution

保留 osslab-manager skill，新增 Python 標準庫 CLI `osrelay`、SQLite 與獨立 runner。Codex／Claude Code 在 Paseo 的既有 session 都呼叫同一 CLI。首版不自動喚醒或新建任何經理 session。

決策來源：本次使用者核准開始開發；施工／審查配置沿用 skill；本次產品交付的最終外部審查另指定 GLM-5.3。使用者補充首版不用自動喚醒，完成後要放進 Paseo 使用。

## User Stories / Acceptance

1. 經理以 repo、工單、穩定 owner 建立任務，重開 session 後能查到狀態、歷史、回執與下一步。工單 ID 全域唯一，workdir 以真實 Git 根路徑正規化。
2. run/review/verify 使用明確 idempotency key。相同 key＋相同請求回同一 attempt；相同 key 不同請求拒絕。不同任務不能同時占用同一 worktree。worker 和 review/verify 也不得交錯寫同一 worktree。
3. 每次 attempt 凍結工單、整份 skill、路由模型資訊與輸入／輸出證據。路由模型以既有 helper 為正本，不另外新增模型呼叫方式。
4. 獨立 `serve` 擁有執行生命週期。經理 CLI 退出不影響已排程工作；程序 PID 必須搭配 starttime 與 boot id。完成結果先原子寫檔，daemon 重啟可重新收取；不假裝 OS spawn 與 SQLite 是同一交易。
5. 啟動後尚未登錄程序就中斷、程序消失且無結果等狀況進 recovery_required，不自動重派。進程仍活著或工作樹鎖仍有人持有時不可 recover。recover 先用既有 helper 建立完整備份，成功後由經理明確選擇繼承現況，再允許新 attempt；不自動 reset/clean/kill。
6. 工單與 review prompt 不得是 worktree 內未追蹤且未 ignore 的檔（會改變指紋），create／review 拒絕。
   worker exit 0 只進 awaiting_acceptance。verify 必須有 schema 2 證據且 passing、版本未變；review 要有非空報告且不改工作樹。accept 需要本 task 驗過的每一條不同命令其最新一次在同版本成功、同版本成功的 review（未跑過任何 review 時可由經理以理由豁免，低階工單用），以及經理的核實註記。這些存在性／版本檢查不能取代經理判斷測試 oracle 與審查意見。
   accept 成功後 state=accepted、保留 worktree 占用；經理自行 commit 後以 finalize 核對 `--commit` SHA 是
   目前 HEAD、工作樹乾淨（tracked／staged／untracked，ignored 除外），且提交 tree 等於 accept 時保存的預期 tree
   （暫存 GIT_INDEX_FILE 從 HEAD 收錄 tracked 刪改與 untracked、排除 ignored，不動真 index），且 SHA 為 accepted
   base 的直接單親子提交；沒有 diff 的驗收允許仍在原 HEAD 結案。通過後才 state=done、記 commit SHA event 並釋放
   reservation。同一 SHA 重送冪等；錯 SHA、內容不符、髒工作樹、錯 owner 拒絕且保留占用。accepted 不能再
   run／verify／review；block／handoff 對 accepted 回 invalid_state，用 finalize 或 abandon 明確退出；舊 done 不假造提交證明。
7. block 保存原因、續辦資訊、喚醒條件（純描述）；unblock 由人／經理明確操作，不自動喚醒。handoff 原子關閉原任務並建立後繼任務、轉移 owner 與工作樹占用；保留鏈與證據，不遺失責任。abandon 在無進行中 attempt、非 recovery_required 時不經驗收關閉任務並釋放占用，保留證據與事件，不動工作樹。
8. `context --runtime codex|claude` 產生接手資訊；角色 owner 與 runtime/session 分開記錄。Paseo workspace 的兩種經理都能讀狀態並操作 CLI，不修改 Paseo provider 的模型或權限配置。

## Implementation Decisions

- Linux 單機、Python 3.11+、SQLite WAL。預設 state 在 `~/.local/state/osslab-relay`；DB 與 artifacts 在 repo 外，目錄只給使用者存取。
- runner 由 systemd user 或 Paseo managed terminal 持有，`serve` 是前景長程序，不用 nohup。全域 daemon lock 防同一 state 重啟出兩個 runner。
- worktree OS lock 存於該 worktree 的 Git directory；attempt 子程序持有 fd，daemon 意外死亡也不能讓第二個 worker闖入。
- task、attempt、events 分離；錯誤有機器可讀 code。wait 在程式內等待，逾時有明確結果，不把等候逾時當成工人失敗。
- 凍結的 worker 工單以原工單內容加本輪回執路徑傳入；worker 不改動原工單、不挪目錄。保留 helper 全部既有授權／秘密規則。
- v1 固定從零啟動 worker。v1.2（`relay-v1.2.md`）改為明示 `--resume` 且門檻不過就拒絕；沒帶 `--resume` 仍從零開始。
- 以既有 evidence-run 指紋契約比對受驗版本；ignored 檔、submodule 內部與外部服務不在指紋內。
- graceful daemon stop 停止接新單，等待其已啟動的子程序完成；故障重啟只核對／收取，不自動清理或重試。
- CLI mutations 需匹配任務 owner（同使用者操作契約，不宣稱是惡意程式的權限隔離）。

## Testing Decisions

Committed regression：以 CLI、真正臨時 Git repo、SQLite、假 model CLI／fixture skill 測主路徑與故障，不呼叫付費模型。覆蓋 competing owners/worktree、idempotency、freeze、manager exit、runner restart、失聯、alive lock、backup failure、stale evidence、empty review、blocked/handoff transaction。

Fresh verification：`make test` 全套、`make check` 編譯與 diff 衛生；GLM-5.3 審查後有修改就重驗受影響路徑。原始 logs 留 Git 外，摘要進驗證報告。

Business acceptance：透過 Paseo managed terminal 跑 runner 與 CLI，確認關掉呼叫端後結果仍可收取；Paseo Codex／Claude Code 各一個限定範圍 smoke session，只讀／操作拋棄式 fixture。若 provider 不可用，明確列未驗，不宣稱兩種都已驗。

## Out of Scope

跨主機調度、自動喚醒經理、自動 fallback、自動重派、自動還原／刪除、模型 API 代理、Paseo UI 改版、production 業務操作。保留原 osslab-manager skill，不取代它的判斷規則。
