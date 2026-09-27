# OSSLab Manager · 工單托管（Claude／ZCode／Codex／Cursor 經理通用版）

一個 agent skill：讓你的主力模型當專案經理，不當碼農。經理先盤點現況，把需求拆成一張張可驗收的工單，派給更便宜的編程 Agent 實現；經理自己重跑每條驗收命令，再交給另一家廠商的模型做唯讀異族 code review、逐條核實；最後逐張本機提交，把關到底。

本 repo 是 **opus-manager**（Claude 經理版）與 **astra-manager**（Codex 經理版）整併後的延續版：四種 runtime（Claude／ZCode／Codex／Cursor）共用同一份 skill，差異只剩一小段執行環境說明。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。

## 為什麼

強模型最值錢的能力是判斷：怎麼拆任務、什麼算做完、審查意見裡哪條是真 bug。寫實作碼最耗額度，而這部分交給按量付費的模型也能做好。

用這個 skill，經理的額度只花在刀刃上：盤點、規劃、驗收、核實審查意見；實作碼由工人模型寫，審查交給異族模型看。

## 實測經驗

- **大型開發確實超省成本**：經理額度只花在盤點、拆單、驗收、核實，實作由便宜的按量工人扛，多張票還能用獨立 worktree 平行跑。
- **正確性不錯，應該比單開發還精準**：每張票都要過「驗收命令重跑＋異族審查＋逐條核實」三層獨立檢查；單開發是同一個模型寫完自己看，盲點一模一樣。管線逼你把「什麼算做完」寫成命令，這件事本身就消掉一大類模糊。

## 推薦組合（harness 與模型）

| 角色 | 建議 | 備註 |
|---|---|---|
| 經理 harness | Claude Code／Codex／ZCode／Cursor 任一 | 四 runtime 共用同一份 skill |
| 經理模型（訂閱制） | Claude **Opus 5.5 以上**，或 **GPT-6 Astra**；思考等級 **high 以上** | 經理的價值全在判斷（拆單、驗收、核實），這層不要省 |
| 工人（sub） | **DeepSeek 4.1 Flash**（pi 無頭、按量計費） | 便宜跟快，就它 |
| 審查 | **Grok** 或 **GLM** 等都不錯 | 審查意見差異不大；挑一個跟經理／工人不同家的（異族）即可 |

## 三個角色

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 經理 | Claude Code／ZCode／Codex（GPT-6 Astra）／Cursor，載入本 skill | — |
| 施工（預設） | pi CLI 無頭模式；`deepseek/deepseek-v4.1-flash` 走 OpenRouter（按量計費） | `scripts/pi-openrouter-worker.sh <workdir> <ticket>` |
| 施工（備援） | ZCode CLI 無頭模式；`GLM-5.3-Flash`（BigModel Coding Plan） | `scripts/zcode-cloud-worker.sh <workdir> <ticket>` |
| 審查 | Grok Build `grok-4.7`（medium），唯讀 Read／Grep；也可換 GLM | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |

## 快速開始

1. 把本 repo 放到你的 agent skill 目錄（例如 `~/.agents/skills/osslab-manager/`，各 runtime view 同源掛載）。
2. 準備兩個 secret 檔（金鑰不進 argv／log／git）：
   - `~/.openclaw/secrets/openrouter.env`：`OPENROUTER_API_KEY=...`
   - `~/.openclaw/secrets/glm-coding-plan.env`：`ZHIPU_API_KEY=...`
   - ZCode CLI 位置可用 `ZCODE_CLI_BIN` 覆蓋。
3. 需要本機裝好 `pi`、`zcode` CLI；審查用 `grok`（或換 GLM 類的唯讀審查）。
4. 在對話裡說「托管」「走工單」「派出去」，經理就會照 skill 跑。

## 流程

盤點（先量再問）→ 決策就緒（已定／觀察／未定三分類）→ 拆單（一張一事、`blocked-by` 完整依賴、驗收寫命令與預期輸出、`review-tier` 預估分級）→ 派工（乾淨環境、凍結 helper 可選、死單有收屍流程）→ 經理驗收（回執只是說法，命令自己重跑）→ 異族審查（高階單跑 Grok，低階單跳過）→ 逐條核實（審查員常看錯）→ 逐張本機提交（阻擋級不得拆單繞過；已核實小 nit 可經理直修）→ push 前整批 code-review → PR。

工單放 `_tickets/open|doing|done/`（目錄即狀態），回執放 `_receipts/`，執行紀錄放 `~/.local/state/osslab-manager/`。

## 與 upstream（yanauto/opus-manager）的差異

- 工人路由預先定好（不逐案摸索）：DeepSeek 預設、GLM 備援、Grok 唯讀審查
- 四 runtime 通用：Claude／ZCode／Cursor 用 Bash 背景、Codex 用受管 session
- 先量再問：盤點產出缺口表，人選範圍；拆單「人管範圍、經理管粒度」
- 工單有 `blocked-by` 依賴欄，只派已解除的單；不同 worktree 平行跑不同鏈
- 審查分級（`review-tier`）：動到斷言／guard／錢權類一律高階；只升不降
- 經理直修：已核實的小 nit 經理可直接改（≤10 行、不改行為），不再 T1→T1r→T1rr
- doing 死鎖回收：PID 重用檢查、半套改動存 patch、重派記在同一張單
- 驗收閘門：逐張提交前要過驗收＋verify＋審查核實；阻擋級成立項不得拆單繞過
- 施工只准 helper CLI：宿主 subagent（Claude Task／Codex subagent／Cursor Task）一律禁用，保住隔離邊界
- helper 金鑰不進 argv、工人以乾淨環境啟動、stdin 接 /dev/null
- 時區一律台灣（+0800）

## 環境假設

SKILL.md 提到的 `develop → implement → verify-change → code-review` 是我們內部的配套 skill 鏈，外部使用者可換成自己的開發流程；grill／to-spec 等對齊工具同理。金鑰路徑與模型路由改 `scripts/` 開頭幾行即可。

## License

MIT，見 [LICENSE](LICENSE)。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。
