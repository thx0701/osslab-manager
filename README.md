# OSSLab Manager · 工單托管（Claude／ZCode／Codex／Cursor 經理通用版）

你買最強的模型，因為需要它的**判斷力與持續力**——給它一個 goal，它真的能把一件事從頭做到尾。但直接讓它埋頭做，額度像倒水：實作碼最耗 token，context 一長方向就漂，goal 一亂就整個 session 燒進去。

這個 skill 把強模型放在它最值錢的位置：**當經理，不當碼農**。你給 goal，它盤點現況、拆成一張張可驗收的工單，派給便宜的按量工人實作；每張單它親自重跑驗收命令、交給異族模型唯讀審查、逐條核實，最後逐張本機提交。強模型的每一分額度都花在判斷上，實作成本被工人壓住，品質被閘門夾住——**goal 再大，燒的是 DeepSeek Flash，不是你的 Opus 訂閱**。

> A manager skill for coding agents: hand your strongest model a goal. It inventories the repo, splits the goal into verifiable tickets, dispatches cheap pay-per-use workers, re-runs every acceptance command itself, gets an out-of-family model to do a read-only review, and commits ticket by ticket. Strong-model judgment, flash-tier implementation cost.

## 給 goal 的三要素

goal 停在經理層；往下每一張工單都是帶驗收命令與預期輸出的契約。想讓經理接得住，把三件事講清楚：

1. **邊界**：什麼不算在內。goal＝授權範圍，沒邊界的 goal 授權過大。
2. **成功訊號**：做完你會觀察到什麼。這是經理的驗收錨點，你不用自己寫命令。
3. **權威契約**：哪份 spec／文件是決策正本。已定的決策直接沿用，不重問。

例：「把 FB 賣貨便上架補到 spec 完整覆蓋。不含金流與物流。做完每個品項在賣場都看得到對應規格與狀態。正本：`docs/listing-spec.md`。」

未定的業務規則（錢、權限、違約條款…）經理會一次一題回來問你——那不是摩擦，是管線在擋「AI 發明業務規則」。

## 實測經驗

- **成本結構被翻轉**：實作走按量計費的 Flash 級工人（同票對照 DeepSeek Flash 小票快約 7 倍），強模型額度只花在盤點、拆單、驗收、核實；多張票還能用獨立 worktree 平行跑。
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
4. 在對話裡說「托管」「走工單」「派出去」，丟出帶三要素的 goal，經理就會照 skill 跑。

## 流程

一個 goal（三要素）→ 盤點（先量再問，缺口表讓你選範圍）→ 決策就緒（已定／觀察／未定三分類，未定的回來問你）→ 拆單（一張一事、`blocked-by` 完整依賴、驗收寫命令與預期輸出、`review-tier` 預估分級）→ 派工（乾淨環境、凍結 helper 可選、死單有收屍流程）→ 經理驗收（回執只是說法，命令自己重跑）→ 異族審查（高階單跑 Grok，低階單跳過）→ 逐條核實（審查員常看錯）→ 逐張本機提交（阻擋級不得拆單繞過；已核實小 nit 可經理直修）→ push 前整批 code-review → PR。

工單放 `_tickets/open|doing|done/`（目錄即狀態），回執放 `_receipts/`，執行紀錄放 `~/.local/state/osslab-manager/`。

## 什麼時候不要用

- 小修一行、改個文案——直接做，別付拆單成本（skill 本身也這麼要求：平時照常自己動手）。
- 探索型 spike：連「做完長什麼樣」都還說不清楚，寫不出驗收。
- 決策密集的工作：每張單都要人拍板，經理只是傳聲筒——先談清楚再進管線。

## 安全邊界

- 工人以**乾淨環境**啟動（不繼承經理 session 的 token 與業務憑證）；金鑰只走環境變數，不進 argv／log／git。
- 審查員**唯讀**（Read／Grep、deny MCP 工具），不得改檔。
- 施工只准 helper CLI；宿主 subagent（Claude Task／Codex subagent／Cursor Task）一律禁用——它們跑在經理進程裡，繞過整個隔離設計。

## 與 upstream（yanauto/opus-manager）的差異

- 工人路由預先定好（不逐案摸索）：DeepSeek 預設、GLM 備援、Grok 唯讀審查
- 四 runtime 通用：Claude／ZCode／Cursor 用 Bash 背景、Codex 用受管 session
- 先量再問：盤點產出缺口表，人選範圍；拆單「人管範圍、經理管粒度」
- 工單有 `blocked-by` 依賴欄，只派已解除的單；不同 worktree 平行跑不同鏈
- 審查分級（`review-tier`）：動到斷言／guard／錢權類一律高階；只升不降
- 經理直修：已核實的小 nit 經理可直接改（≤10 行、不改行為），不再 T1→T1r→T1rr
- doing 死鎖回收：PID 重用檢查、半套改動存 patch、重派記在同一張單
- 驗收閘門：逐張提交前要過驗收＋verify＋審查核實；阻擋級成立項不得拆單繞過
- helper 金鑰不進 argv、工人以乾淨環境啟動、stdin 接 /dev/null
- 時區一律台灣（+0800）

## 環境假設

SKILL.md 提到的 `develop → implement → verify-change → code-review` 是我們內部的配套 skill 鏈，外部使用者可換成自己的開發流程；grill／to-spec 等對齊工具同理。金鑰路徑與模型路由改 `scripts/` 開頭幾行即可。

## License

MIT，見 [LICENSE](LICENSE)。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。
