# OSSLab Relay

`osrelay` 是 [osslab-manager](https://github.com/thx0701/osslab-manager) 的本機執行底座；公開版放在該 repo 的 `relay/` 子目錄，可直接在子目錄執行 `python3 deploy/install-user.py` 安裝。
經理判斷需求、審查與驗收；Relay 保管派工、程序、等待、恢復、阻塞與交接。
Codex／Claude Code 在既有 session 呼叫同一 CLI（Paseo 上或一般終端機皆可）；Relay 不喚醒、不新建經理，自動開下一段由 Paseo 的 `create_agent` 負責。

需要 Linux、Python 3.11+、Git，以及已安裝的 osslab-manager skill 和它依賴的模型 CLI。
Python runtime 沒有第三方依賴。SQLite 與執行證據預設放在 `~/.local/state/osslab-relay`。

## 開始使用

開發版可直接 `./bin/osrelay --help`。部署與 Paseo 的完整操作見 [Paseo guide](docs/paseo.md)。

```sh
osrelay doctor
osrelay goal create --id goal-001 --owner project-manager --note '確認清單'
osrelay create --workdir /path/to/worktree --ticket /path/to/ticket.md --owner project-manager --id ticket-001 --goal goal-001 --chain chain-a
osrelay run ticket-001 --owner project-manager --key implementation-1
# 接續這張單上一個成功 pi 工人的 session（與 --chain 無關）；HEAD 未變、回執無存疑才准，門檻不過會拒絕
osrelay run ticket-001 --owner project-manager --key implementation-2 --resume
osrelay context goal-001 --runtime codex
# 從上一個 JSON result.id 取得 attempt ID
osrelay wait attempt-... --timeout 30
osrelay context ticket-001 --runtime codex
```

所有輸出是 JSON。退出碼 0 表示 CLI 操作成功，**不是任務驗收通過**；例如 `wait`
成功傳回 `failed` attempt 仍退出 0。退出碼 3 是等候逾時，工作繼續；一般執行錯誤退出 1，命令列用法錯誤退出 2。
查看 `result.status`、`result.state` 與錯誤 `error.code` 判斷下一步。

## 模型與驗收

每次 attempt 複製整份 skill，記錄 helper hash、工單、route、程序身份、stdout/stderr 與結果。
工人預設 pi／DeepSeek v4.1 Flash high；經理可明確指定 `--engine glm` 使用 skill 的 GLM-5.3-Flash。
日常 `review` 仍由 Grok 4.7 medium 執行。實際值以凍結 helper 為正本，Relay 不自行改模型或 fallback。
本專案交付的外部審查另由使用者指定 GLM-5.3。

```sh
osrelay verify ticket-001 --owner project-manager --key verification-1 -- make test
osrelay review ticket-001 --owner project-manager --key review-1 --prompt /path/to/review-prompt.md
# 等待各 attempt 結束、逐條閱讀並核實證據後
osrelay accept ticket-001 --owner project-manager --note '已核實驗證與審查，逐項符合工單'
# accept 通過 state=accepted，保留 worktree 占用；經理自行 commit 後再 finalize
osrelay finalize ticket-001 --owner project-manager --commit <SHA> --note '已自行提交'
```

`accept` 失敗不改變狀態；成功後 `state=accepted`，仍占著 worktree，其他任務不能排入。
經理依原本流程自行 `git commit`，再 `finalize`。Relay 不代 commit；finalize 核對 `--commit` SHA 是
目前 HEAD、工作樹已乾淨（追蹤、暫存、未追蹤都在意，ignored 除外），且該提交的 tree 等於 accept
時保存的預期 tree（用暫存 index 從 HEAD 收錄改動、刪除與未追蹤檔，不動真 index）。SHA 必須是
accepted base 的直接單親子提交；沒有 diff 的驗收允許在原 HEAD 結案。同一 SHA 重送冪等，錯 SHA、
內容不符、髒工作樹或錯 owner 都拒絕且保留占用。`accepted` 不能再 run/verify/review；用 `finalize`
或 `abandon` 收尾。舊 `done` 任務不會被 finalize 假造提交證明。

`accept` 要求目前 Git 指紋與成功驗證／review 一致，且證據檔未被換掉。這個 task 驗過的**每一條不同命令**，
最新一次都必須在目前版本通過；後跑的命令通過不能蓋掉先前失敗的命令。
低階工單（只走 code-review、不跑 Grok）可 `accept ... --review-waiver '<理由>'`；該 task 一旦跑過 review
（成功或失敗）就不能再豁免，審查分級只升不降。

工單與 review prompt 若放在 worktree 內，必須已 git-ignore 或已提交；未追蹤檔會算進指紋，
`create`／`review` 會以 `inside_worktree` 拒絕。經理自己的審查報告副本、核實筆記同樣放 worktree 外。
review 有非空報告不代表「沒有問題」；經理仍須判斷 findings、測試 oracle 和業務驗收。
ignored 檔、submodule 內部及外部服務不在指紋中，不能用它們假裝涵蓋所有環境。

## 中斷與交接

```sh
osrelay recover ticket-001 --owner project-manager --note '看過半成品與備份，下一輪繼承現況'
osrelay block ticket-001 --owner project-manager --reason '等規格' --resume-note '從驗收第 3 條續辦' --wake-condition '使用者補上答案'
osrelay unblock ticket-001 --owner project-manager --note '規格已定'
osrelay handoff ticket-001 --owner project-manager --to next-manager --key handoff-1 --note '接續事項與證據'
osrelay abandon ticket-001 --owner project-manager --note '改由 ticket-002 處理'
```

交接在同一 SQLite 交易內關閉舊任務、建立後繼任務、移轉 worktree 占用。它不發訊息、不開 session。
`abandon` 不經驗收關閉任務並釋放 worktree 占用；不 reset/clean 工作樹，半成品留給經理依授權處理。
有進行中 attempt 或 recovery_required 時拒絕（先 cancel／recover）。
owner 是穩定角色；Paseo session ID 另以 `bind` 記錄。相同請求重送同一 key，不會再次執行。

失聯不自動重派。`recover` 先備份目前工作樹；程序／同 session 的子程序仍在，或 worktree lock
仍被占用，就拒絕恢復。僅繼承現況，不 reset/clean/kill。若尚在 queued，可 `cancel <attempt> --owner ... --note ...`。
已開始的程序由經理查明原因後人工處理；Relay 不提供無條件 kill。

同一主機以**一份 state** 管理同一組 worktree。OS lock 可防另一份 state 同時執行，
但不同 DB 不共享任務占用／歷史，不能作為正常多經理用法。請勿在 Relay 管理期間另走舊 helper 派同一工作樹。

## 開發

`make test` 執行真 Git／SQLite／程序的 CLI regression；模型使用離線 fixture。
`make check` 檢查編譯與 diff。規格見 [spec](docs/specs/relay-v1.md)。

設計參考 [OpenRig](https://github.com/mvschwarz/openrig) 的持久角色與交接概念；本專案是獨立實作。
最大項、鏈與有條件 `--resume` 的契約見 [v1.2](docs/specs/relay-v1.2.md)。
