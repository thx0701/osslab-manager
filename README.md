# OSSLab Manager · 強模型當技術長，Flash 當 junior（Claude／ZCode／Codex／Cursor 通用）

**中文** | [English](README.en.md)

你想要的是一個**資深技術長帶 junior 工程師**的團隊：技術長的判斷力與持續力都在，junior 的成本與速度也都在。

這個 skill 就是這個團隊。強模型（Opus 5.5+／GPT-6 Astra）當**技術長**：盤點現況、拆工單、定驗收，不寫實作碼——它的每一分額度都花在判斷上。便宜快速的 Flash 級模型當 **junior 工程師**埋頭寫碼。再找另一家廠商的模型做外部唯讀 code review，技術長逐條核實、親自重跑每條驗收命令，逐張提交。

**資深的判斷，junior 的成本**——goal 再大，燒的是 DeepSeek Flash，不是你的 Opus 訂閱。

> A tech-lead skill for coding agents: your strongest model plays the senior tech lead — it inventories the repo, splits the goal into verifiable tickets, dispatches cheap flash-tier juniors to implement, re-runs every acceptance command itself, gets an out-of-family model to review read-only, and commits ticket by ticket. Senior judgment, junior cost.

## 給 goal 的三要素

goal 停在技術長這層；往下每一張工單都是帶驗收命令與預期輸出的契約。想讓技術長接得住，把三件事講清楚：

1. **邊界**：什麼不算在內。goal＝授權範圍，沒邊界的 goal 授權過大。
2. **成功訊號**：做完你會觀察到什麼。這是技術長的驗收錨點，你不用自己寫命令。
3. **權威契約**：哪份 spec／文件是決策正本。已定的決策直接沿用，不重問。

例：「把 FB 賣貨便上架補到 spec 完整覆蓋。不含金流與物流。做完每個品項在賣場都看得到對應規格與狀態。正本：`docs/listing-spec.md`。」

未定的業務規則（錢、權限、違約條款…）技術長會一次一題回來問你——那不是摩擦，是管線在擋「AI 發明業務規則」。

## 實測經驗

- **成本結構被翻轉**：實作走按量計費的 Flash 級 junior（同票對照：DeepSeek Flash 比 GLM-5.3-Flash 小票快約 7 倍），技術長的額度只花在盤點、拆單、驗收、核實；多張票還能用獨立 worktree 平行跑。
- **正確性比單開發精準**：每張票都要過「驗收命令重跑＋異族審查＋逐條核實」三層獨立檢查；單開發是同一個模型寫完自己看，盲點一模一樣。管線逼你把「什麼算做完」寫成命令，這件事本身就消掉一大類模糊。
- **代價只有時間**：一張中型票從派單到三輪審查結束約 1.5 小時，急件不適合；其他成本都低。非常值得。

### 案例：browser-workflow（瀏覽器租用與人工接手）

28 個檔、+5,091 行；4 張工單（T1 加 3 張修復單）、3 輪 Grok 審查，約 1.5 小時，最後 60 個測試全過、合成一個 commit。

- junior 自己寫的 57 個測試全綠，但第一輪審查找出 8 條成立的問題；技術長另寫重現腳本，抓到續租會卡住、父程序結束後留下孫程序。
- 第二輪再抓到 2 條阻擋級問題：正式 wrapper 可以被繞過、不送 signal；寫入與讀取的格式不一致，重啟後 state 損毀（修前 3 筆非法輸入全被接受、重啟 `corrupt_state`；修後全拒、重啟正常）。
- 第三輪零問題才提交。

這些都是「測試全綠但實際有錯」的缺陷——同一個模型寫完自己看，很難抓到。

## 推薦組合（harness 與模型）

| 角色 | 建議 | 備註 |
|---|---|---|
| 技術長 harness | Claude Code／Codex／ZCode／Cursor 任一 | 四 runtime 共用同一份 skill |
| 技術長模型（訂閱制） | Claude **Opus 5.5 以上**（思考等級 **high 以上**），或 **GPT-6 Astra**（固定 **medium**：實測每步比 xhigh 快約 3 倍） | 技術長的價值全在判斷（拆單、驗收、核實），這層不要省 |
| junior 工程師（sub） | **DeepSeek 4.1 Flash**（pi 無頭、按量計費） | 便宜跟快，就它 |
| 外部審查 | **Grok** 或 **GLM** 等都不錯 | 審查意見差異不大；挑一個跟技術長／junior 不同家的（異族）即可 |

## 三個角色

（SKILL.md 內文以「經理」稱技術長、「工人」稱 junior——同一個角色，對外講人話。）

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 技術長 | Claude Code／ZCode／Codex（GPT-6 Astra）／Cursor，載入本 skill | — |
| junior（施工・預設） | pi CLI 無頭模式；`deepseek/deepseek-v4.1-flash` 走 OpenRouter（按量計費） | `scripts/pi-openrouter-worker.sh <workdir> <ticket>` |
| junior（施工・備援） | ZCode CLI 無頭模式；`GLM-5.3-Flash`（BigModel Coding Plan） | `scripts/zcode-cloud-worker.sh <workdir> <ticket>` |
| 外部審查 | Grok Build `grok-4.7`（medium），唯讀 Read／Grep；也可換 GLM | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |

## 快速開始

1. 把本 repo 放到你的 agent skill 目錄（例如 `~/.agents/skills/osslab-manager/`，各 runtime view 同源掛載）。
2. 準備兩個 secret 檔（金鑰不進 argv／log／git）：
   - `~/.openclaw/secrets/openrouter.env`：`OPENROUTER_API_KEY=...`
   - `~/.openclaw/secrets/glm-coding-plan.env`：`ZHIPU_API_KEY=...`
   - ZCode CLI 位置可用 `ZCODE_CLI_BIN` 覆蓋。
3. 需要本機裝好 `pi`、`zcode` CLI；審查用 `grok`（或換 GLM 類的唯讀審查）。
4. 在對話裡說「托管」「走工單」「派出去」，丟出帶三要素的 goal，技術長就會照 skill 跑。

## 流程

一個 goal（三要素）→ 盤點（先量再問，缺口表讓你選範圍）→ 決策就緒（已定／觀察／未定三分類，未定的回來問你）→ 拆單（一張一事、`blocked-by` 完整依賴、驗收寫命令與預期輸出、`review-tier` 預估分級）→ 派工（乾淨環境、凍結 helper 可選、死單有收屍流程）→ 技術長驗收（回執只是 junior 的說法，命令自己重跑）→ 異族審查（高階單跑 Grok，低階單跳過）→ 逐條核實（審查員常看錯）→ 逐張本機提交（阻擋級不得拆單繞過；已核實小 nit 技術長可直修）→ push 前整批 code-review → PR。

工單放 `_tickets/open|doing|done/`（目錄即狀態），回執放 `_receipts/`，執行紀錄放 `~/.local/state/osslab-manager/`。

## 長 session

不是每個段落都換 session：PR 已 merge、你叫停、卡在等你決定，或這則跑了約 3 小時（runtime 有回報時再加 context 約 60%），技術長才把約 2KB 的交接寫進 `~/.local/state/osslab-manager/handoffs/`，換一則新 session。新 session 只核 HEAD 與下一張工單，不重新盤點。你在 Paseo 上已經下了 goal（或 Codex `/goal`）時，技術長自己開下一則；否則它停下，把可貼上的開頭交給你。做法在 SKILL.md「九、長 session」。

等工人時一次等到底，不幾秒問一次進度；Codex 技術長固定用 medium。

給團隊的時間戳用台灣時間（+0800）；主機時鐘跑 UTC，helper 已內建 `TZ=Asia/Taipei`。Grok 仍是預設唯讀審查。

## 什麼時候不要用

- 小修一行、改個文案——直接做，別付拆單成本（skill 本身也這麼要求：平時照常自己動手）。
- 探索型 spike：連「做完長什麼樣」都還說不清楚，寫不出驗收。
- 決策密集的工作：每張單都要人拍板，技術長只是傳聲筒——先談清楚再進管線。

## 安全邊界

- junior 以**乾淨環境**啟動（不繼承技術長 session 的 token 與業務憑證）；金鑰只走環境變數，不進 argv／log／git。pi junior 另以精簡模式啟動：不載入 skill 與擴充，也不自動載入任何一層的 AGENTS.md；repo 自己的規矩由指示要求它讀。
- 審查員**唯讀**（Read／Grep、deny MCP 工具），不得改檔。
- 施工只准 helper CLI；宿主 subagent（Claude Task／Codex subagent／Cursor Task）一律禁用——它們跑在技術長進程裡，繞過整個隔離設計。

## 與 upstream（yanauto/opus-manager）的差異

- 工人路由預先定好（不逐案摸索）：DeepSeek 預設、GLM 備援、Grok 唯讀審查
- 四 runtime 通用：都在背景派工；Claude Code／ZCode 等完成通知、Codex 用受管 session 與 code-mode 迴圈、Cursor 前景跑 `wait-worker.sh`
- 先量再問：盤點產出缺口表，人選範圍；拆單「人管範圍、技術長管粒度」
- 工單有 `blocked-by` 依賴欄，只派已解除的單；不同 worktree 平行跑不同鏈
- 審查分級（`review-tier`）：動到斷言／guard／錢權類一律高階；只升不降
- 技術長直修：已核實的非阻擋小 nit 可直接改（≤10 行、不改行為）；只複述既有行為的文案（README、驗證報告）約 20 行內也可直接改，回執與 spec 不行；一輪審查的成立項合成一張修復單，不再一條一單（阻擋級照舊走 junior）
- doing 死鎖回收：PID 重用檢查、半套改動存 patch、重派記在同一張單
- 驗收閘門：逐張提交前要過驗收＋verify＋審查核實；阻擋級成立項不得拆單繞過
- helper 金鑰不進 argv、乾淨環境啟動、stdin 接 /dev/null
- 團隊時間戳用台灣時間（+0800）

## 環境假設

SKILL.md 提到的 `develop → implement → verify-change → code-review` 是我們內部的配套 skill 鏈，外部使用者可換成自己的開發流程；grill／to-spec 等對齊工具同理。金鑰路徑與模型路由改 `scripts/` 開頭幾行即可。

## License

MIT，見 [LICENSE](LICENSE)。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。
