# OSSLab Manager · 工單托管（Claude／ZCode／Codex 經理通用版）

一個 agent skill：讓你的主力模型當專案經理，不當碼農。經理先盤點現況，把需求拆成一張張可驗收的工單，派給更便宜的編程 Agent 實現；經理自己重跑每條驗收命令，再交給另一家廠商的模型做唯讀異族 code review、逐條核實；最後逐張本機提交，把關到底。

本 repo 是 **opus-manager**（Claude 經理版）與 **astra-manager**（Codex 經理版）整併後的延續版：三種 runtime 共用同一份 skill，差異只剩一小段執行環境說明。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。

## 為什麼

強模型最值錢的能力是判斷：怎麼拆任務、什麼算做完、審查意見裡哪條是真 bug。寫實作碼最耗額度，而這部分交給按量付費的模型也能做好。

用這個 skill，經理的額度只花在刀刃上：盤點、規劃、驗收、核實審查意見；實作碼由工人模型寫，審查交給異族模型看。

## 三個角色

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 經理 | Claude Code／ZCode／Codex（GPT-6 Astra），載入本 skill | — |
| 施工（預設） | pi CLI 無頭模式；`deepseek/deepseek-v4.1-flash` 走 OpenRouter（按量計費） | `scripts/pi-openrouter-worker.sh <workdir> <ticket>` |
| 施工（備援） | ZCode CLI 無頭模式；`GLM-5.3-Flash`（BigModel Coding Plan） | `scripts/zcode-cloud-worker.sh <workdir> <ticket>` |
| 審查 | Grok Build `grok-4.7`（medium），唯讀 Read／Grep | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |

## 快速開始

1. 把本 repo 放到你的 agent skill 目錄（例如 `~/.agents/skills/osslab-manager/`，各 runtime view 同源掛載）。
2. 準備兩個 secret 檔（金鑰不進 argv／log／git）：
   - `~/.openclaw/secrets/openrouter.env`：`OPENROUTER_API_KEY=...`
   - `~/.openclaw/secrets/glm-coding-plan.env`：`ZHIPU_API_KEY=...`
   - ZCode CLI 位置可用 `ZCODE_CLI_BIN` 覆蓋。
3. 需要本機裝好 `pi`、`zcode`、`grok` 三個 CLI。
4. 在對話裡說「托管」「走工單」「派出去」，經理就會照 skill 跑。

## 流程

盤點（先量再問）→ 決策就緒（已定／觀察／未定三分類）→ 拆單（一張一事、`blocked-by` 完整依賴、驗收寫命令與預期輸出）→ 派工（乾淨環境、凍結 helper 可選）→ 經理驗收（回執只是說法，命令自己重跑）→ Grok 異族審查 → 逐條核實（審查員常看錯）→ 逐張本機提交（阻擋級不得拆單繞過）→ push 前整批 code-review → PR。

工單放 `_tickets/open|doing|done/`（目錄即狀態），回執放 `_receipts/`，執行紀錄放 `~/.local/state/osslab-manager/`。

## 與 upstream（yanauto/opus-manager）的差異

- 工人路由預先定好（不逐案摸索）：DeepSeek 預設、GLM 備援、Grok 唯讀審查
- 三 runtime 通用：Claude／ZCode 用 Bash `run_in_background`，Codex 用受管 session
- 先量再問：盤點產出缺口表，人選範圍；拆單「人管範圍、經理管粒度」
- 工單有 `blocked-by` 依賴欄，只派已解除的單；不同 worktree 平行跑不同鏈
- 驗收閘門：逐張提交前要過驗收＋verify＋審查核實；阻擋級成立項不得拆單繞過
- helper 金鑰不進 argv、工人以乾淨環境啟動、stdin 接 /dev/null
- 時區一律台灣（+0800）

## 環境假設

SKILL.md 提到的 `develop → implement → verify-change → code-review` 是我們內部的配套 skill 鏈，外部使用者可換成自己的開發流程；grill／to-spec 等對齊工具同理。金鑰路徑與模型路由改 `scripts/` 開頭幾行即可。

## License

MIT，見 [LICENSE](LICENSE)。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。
