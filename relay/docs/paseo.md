# Paseo integration

Relay 是主機上的共用 CLI，不是另一個 Paseo provider；不在 Paseo 的 Codex／Claude Code 終端機 session 也能用，
Paseo 只多自動接段（經理用 `create_agent` 開下一段）。既有 Codex／Claude Code session
可直接呼叫；模型與權限沿用該 session。Codex 經理 reasoning medium，施工／日常 review 沿用 osslab-manager。
不修改 Paseo server、provider、MCP 設定，也不需要重啟 Paseo。

## 部署

先完成 review、commit、push／PR，再從已審查 checkout 執行。以下以 Relay 目錄為目前目錄
（本 repo 根目錄；公開 osslab-manager repo 則是 `relay/`，或從該 repo 根執行 `python3 relay/deploy/install-user.py`）：

```sh
python3 deploy/install-user.py
systemctl --user daemon-reload
systemctl --user enable --now osrelay.service
osrelay doctor
```

安裝是 Git HEAD 的固定副本，放 `~/.local/share/osslab-relay/releases/<commit>`，CLI 位於
`~/.local/bin/osrelay`（Paseo service 已有此 PATH）。state 在 `~/.local/state/osslab-relay`。
installer 不會起程序，也拒絕未提交來源、覆蓋非 Relay launcher 或不同 service 定義。
更新前確認舊 runner 已排空，再 graceful restart；不要把更新中的 repo 直接當正式 runtime。
升級前也要讓 queued attempt 跑完或先 cancel：舊版排入的 attempt 沒記排隊前狀態，新版 cancel 一律回到 ready。
回退可把 current symlink 指回仍保留的舊 release，再排空／重啟 runner。schema version 2 起，v1 程式會拒絕開啟已升級的 state；要回退就不要先升級，或繼續用帶 version 2 的 release。

若只做 staged smoke，在 Paseo managed terminal 以前景命令運行：

```sh
/path/to/<Relay 目錄>/bin/osrelay --state /outside/repo/relay-smoke-state serve
```

managed terminal 關閉可能停止 runner。需要 session／terminal 之外的持續服務時用 systemd；
worker 為獨立 session，runner 重啟會重新核對，不會自動重跑。

## 經理入口

Paseo workspace 用現有 Git worktree。請對 Codex 或 Claude Code 說：

> 使用 osslab-manager skill，派工與等待改走 osrelay。先 osrelay doctor、osrelay list，
> 有既有任務就 context，讀完整歷史與回執後接手。不要重複派同一工作樹。
> 首版不自動喚醒；照下方「等待」一次等到底，不用短逾時反覆輪詢。

```sh
osrelay create --id project-ticket-001 --owner project-manager --workdir /workspace --ticket /outside/workspace/ticket.md
osrelay bind project-ticket-001 --owner project-manager --runtime codex --session <Paseo-agent-id>
osrelay context project-ticket-001 --runtime codex
```

Claude Code 使用 `--runtime claude`，不改 owner；owner 表示負責角色，session 只是當前承接者。
換 session 先 list/context/bind 即可。真正移交責任用 handoff，後繼任務含 parent 與交接原因。

## skill 配合

保留 osslab-manager：盤點、工單品質、派工引擎選擇、逐條核實與本機 commit 都由 skill 決策。
Relay 路徑用 SQLite 狀態，原 Markdown 工單不挪動；CLI 傳入凍結副本與唯一回執位置。
不可一邊 Relay、一邊手動 helper／搬 _tickets/doing 來控制同一任務。

## 等待

`wait` 每次呼叫都是一輪經理推理，逾時設長、一次等到底：

- Claude Code：背景執行 `osrelay wait <attempt> --timeout 3600`，等 host 完成通知；退出 3 就再背景等一次。
- Codex：單次工具約 30 秒交還；不要用 Shell 一次次跑短逾時的 `wait`。用 code-mode 跑 osslab-manager
  `docs/relay.md` 第 4 點那個 cell（`@exec` 的 `yield_time_ms` 3600000、`osrelay wait <attempt> --timeout 3300`），
  一次呼叫等到 attempt 結束；退出 3（仍在跑）就再跑同一個 cell。
- 其他 host：前景 `wait`，`--timeout` 設得比該 host 單次命令上限短。

工人 attempt 成功只表示 helper 完成且有回執；經理繼續 verify → review → 核實 → accept。
accept 通過後 `state=accepted` 並保留 worktree 占用；經理依原 skill 自行逐張本機 commit，
再 `osrelay finalize <task> --owner ... --commit <SHA> --note ...`，核對 SHA 是目前 HEAD、
工作樹乾淨且提交 tree 等於 accept 時的預期 tree 後才收尾並釋放。Relay 不代 commit。
review findings 若需修改，再 run 新 key、重驗重審。
`recover` 明確接受繼承半成品；備份失敗時不能重派。所有模型 CLI 的憑證仍由原 helper 載入。

## 驗收界線

測試使用獨立 fixture repo/state、Paseo managed terminal，以及真實 Codex／Claude Code session
呼叫 CLI；fixture worker 不接付費 API。provider smoke 證明 host、PATH／絕對路徑、JSON 與接手機制；
不能替代各模型自身的工作品質審查或 production 業務驗收。

## 首版操作限制

- 重送 run 請求時 `--note` 也是請求的一部分，必須逐字相同；要改註記／需求用新 key。
- handoff 保留舊 task 的證據與 parent 鏈，但後繼任務重新進 ready（blocked 則保留 blocked）。
  新 owner 必須在後繼任務重新 verify／review；不自動沿用舊 owner 的驗收。
- cancel 只取消 queued attempt，不釋放 worktree 占用；handoff 轉移占用。暫停用 block；確定不做用
  `abandon --note`，它釋放占用、保留所有證據與事件，不動工作樹。`accepted` 任務必須 `finalize`
  或 `abandon`；不可 block／handoff（會回 `invalid_state`）也不可再 run／verify／review。
  不要修改 DB 或假 accept 來釋放鎖。
- enqueue／accept 的檔案快照仍在短交易內。避免把巨量 build 產物留成 untracked；若遇 database is locked，
  等占用交易結束，再以原 key 重送。不以換 state／繞過鎖解決。
- `systemctl --user stop osrelay.service` 會等待工人排空，掛住的工人不會被無條件殺掉。
  經理先查該 attempt 的 process（PID/starttime/boot_id）及 log，按既有授權處理工人／子程序；
  runner 重新收取為 recovery_required 後，再 recover 備份與繼承。不要只照舊 PID 盲目 kill。
- `doctor` 需要預設 skill 可讀；skill 缺失時以 JSON error 退出 1，先修掛載。查看結構化阻塞資料請用 status/context。
- `ZCODE_CLI_BIN` 可指定既有 helper 的自訂 CLI 路徑；服務啟動前設在 systemd user service 的 Environment，
  修改經理 terminal 的環境不會追溯改掉已運行 runner 的環境。憑證仍由 helper 讀既有 secret 檔。
