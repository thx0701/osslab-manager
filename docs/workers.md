# 工人路由與隔離（SKILL 角色表細節）

> SKILL 本文只留路由規則；這裡是完整角色表、選工人依據、供應商資料流與工人隔離的實作細節。換工人或模型前先問人。

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 施工（預設） | pi CLI 在本機以 RPC 無頭模式執行，由 `scripts/pi-worker-driver.py` 驅動：事件濃縮成一行一筆即時寫進 log、成敗照文字模式判斷；工人可用 `ask_manager`（`scripts/pi-ask-manager.ts`）在施工中問經理，Relay 派工才有通道（見第三節）；模型 `deepseek-v4-1-flash` 走 RunInfra（按量計費，思考 `high`）；精簡啟動，不載入 skill、上層 AGENTS.md 與擴充 | `scripts/pi-runinfra-worker.sh [--resume <接續鍵>] <workdir> <ticket>` |
| 施工（同一模型、舊供應商，只在指定時） | 同上，改走 OpenRouter。不在自動退路裡，使用者指定才用，參數相同 | `scripts/pi-openrouter-worker.sh [--resume <接續鍵>] <workdir> <ticket>` |
| 施工（備援） | ZCode CLI 在本機以 yolo 模式執行；模型 `GLM-5.3-Flash` 走雲端（BigModel Coding Plan 訂閱，思考預設 Max） | `scripts/zcode-cloud-worker.sh [--resume <接續鍵>] <workdir> <ticket>`（不接續，一律從零） |
| 施工（指定） | Claude Code 無頭；模型 `claude-haiku-5-5`、effort `high`，走本機 Pro 訂閱。不載入 skill。啟動事件的模型不符或改走 API key 就失敗 | `scripts/claude-haiku-worker.sh [--resume <接續鍵>] <workdir> <ticket>`（不接續，一律從零；Relay 不路由，見下方選工人） |
| 審查（第一順位） | Codex 唯讀沙箱，`gpt-6-astra`，reasoning effort `medium`：shell 只能讀、不能寫、沒有網路，不載入本機 Codex 設定與 MCP，登入沿用本機 ChatGPT 帳號（和 Codex 經理共用額度） | `scripts/codex-readonly-review.sh <workdir> <prompt-file>` |
| 審查（第二順位） | ZCode，完整 `GLM-5.3`，思考 `max`，只給 Read／Grep | `scripts/zcode-readonly-review.sh <workdir> <prompt-file>`；見 [docs/glm-review.md](glm-review.md) |
| 審查（第三順位） | Grok Build，`grok-4.7`，reasoning effort `medium`，只給 Read／Grep；已停訂，到期前可用 | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |
| 等待（工具） | 阻塞到 pid 結束，只印一行 | `scripts/wait-worker.sh <pid\|worker.log\|review.err> <max_seconds>` |
| 收屍備份（工具） | 保存 binary patch 與未追蹤檔，核對後才准人工清理 | `scripts/backup-worktree.sh <workdir> <全新備份目錄>` |
| 證據（工具） | 跑一條命令，完整輸出與 JSON 信封存檔，stdout 只印摘要 | `scripts/evidence-run.sh <out-dir> <label> -- <命令…>` |
| 驗收（工具） | 照清單依序跑多項檢查，逐項留 log 與 exit code，任一失敗整體非零 | `scripts/acceptance-run.sh <repo 外輸出目錄> <清單>` |

路由已由本安裝定好，不重新摸工人、不另寫 `workers.md`。helper 不用本機自架模型 provider；憑證只從既有 secret 檔載入（`glm-5.3-flash.env`、`openrouter.env`、`glm-coding-plan.env`），不進 argv／log／git。要換模型或工具先問人，再改本 skill 開 PR。

**選工人**：預設 DeepSeek，供應商是 RunInfra（2026-10-04 單輪對照：同一模型的工具第一跳與當時的 OpenRouter 相近或略快、長輸出約快 4～5 倍；OpenRouter 腳本保留）。RunInfra 是針對 agent 工作負載優化的託管服務（同一 session 的呼叫送到已有快取的副本），速度與費用結論只對它成立。2026-10-11 對 Claude Haiku 5.5 的實測見 [docs/benchmarks/2026-10-11-deepseek-vs-haiku.md](benchmarks/2026-10-11-deepseek-vs-haiku.md)。遇到下列情況直接改派 GLM-5.3-Flash 備援（`zcode-cloud-worker.sh`，Relay 是 `--engine glm`），並在 `claimed-by` 與工單「重派」寫實際引擎和原因：RunInfra 暫停、503、啟動失敗、API 錯誤、額度或速率限制；同一張單 DeepSeek 驗收不過且原因像是模型能力；使用者指定。OpenRouter 的同一支 DeepSeek 不在自動退路裡，使用者指定才用。RunInfra 額度用完時另外告訴使用者，要不要調高上限由使用者決定。
Claude Haiku 只在使用者指定時派（`claude-haiku-worker.sh`），不插入上面的自動改派。它吃本機 Claude Pro 額度，和 Claude 經理共用同一個訂閱窗口。經理為 Claude 時，核實段註明同系施工；審查照第五節的順位。`osrelay` 的施工引擎只有 pi／glm，已有 Relay 任務的 worktree 不要改用這支手動派。
程式碼與工單內容會送到該工人的模型供應商（RunInfra／DeepSeek，備援是 BigModel，使用者指定時是 OpenRouter／DeepSeek，指定的 Haiku 是 Anthropic 訂閱），工單照舊不寫秘密。

**工人隔離的邊界**：helper 以乾淨環境變數啟動工人，不繼承經理 session 已匯出的 token 與業務憑證；但工人仍在本機跑 shell，看得到 Docker、網路與磁碟上的檔案（含 secret 檔），「不動 prod」只靠指示。pi 工人另以精簡模式啟動：不載入全域與公司 skill（含通訊與業務系統的）、擴充與 prompt 範本，每一層的 AGENTS.md／CLAUDE.md 都不自動載入（上層共用規矩可能寫著怎麼載入團隊秘密）；repo 自己的 AGENTS.md／CLAUDE.md 改由 helper 指示與工單要求它用 read 去讀，實測會照讀照做。repo 自己的規矩若本身含上層共用段落，工人讀檔時仍會看到，這由指示「不讀取、不輸出秘密」擋。2026-09-27 實測每次請求的 prompt 從約 7.3k token 降到 1.6k，工具照舊 read／bash／edit／write。zcode 備援還沒有對應的精簡開關，照舊載入。指定的 Haiku 工人用私人設定目錄，裡面只有訂閱憑證副本，跑完刪掉；並以 `--safe-mode` 不載入 CLAUDE.md、skill、hooks 與 MCP。它不讀 API key。Claude Code 回報的啟動模型不是 `claude-haiku-5-5`、收工用量不是這個模型、或認證來源是 API key，helper 直接失敗，回執不算數。這版 CLI 可能在 stderr 印 `unrecognized_model`；以 helper 退出碼和用量為準，不拿那行單獨否決。同一原因，CLI 回報的 `total_cost_usd`／`costUSD` 是用 Opus 5.5 價格算的（2026-10-11 實測，`costBasis: unknown`），不能當 Haiku 費用，要算費用用 token 數乘官方價格。CLI 有時會在 `init` 前先送 `ui_invalidate` 之類的 system 事件，helper 會略過（最多 20 個），`init` 前出現其他事件仍拒絕。權限是 `bypassPermissions`（對齊 zcode 的 yolo），不 commit 仍靠工單指示。所以工單不寫秘密或 secret 路徑；凡要碰 prod 的驗證（唯讀煙霧、XML-RPC、瀏覽器）由經理在第四節自己做；給工人拋棄式測試環境，並寫明哪些共用資源不准刪。

## 開發順序與配套 skill（原文）

OSSLab 開發順序照舊：`develop → implement → verify-change → code-review`；外部審查是 code-review 內的獨立意見，不取代它。本文提到的 `grill-with-docs`、`grill-me`、`to-spec`、`to-tickets`、`verify-change`、`code-review` 是配套 skill；host 沒有時，改用工單的驗收命令與預期輸出、第四～六節的重跑與核實收斂，閘門不因缺 skill 而省略。工人不 commit、不 push、不動 prod、不挪工單。可行時給工人獨立 git worktree；不把工人派進別人正在用的髒 checkout。
