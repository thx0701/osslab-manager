# OSSLab Manager · 強模型當技術長，Flash 當 junior（Claude／ZCode／Codex／Cursor 通用）

**中文** | [English](README.en.md)

你想要的是一個**資深技術長帶 junior 工程師**的團隊：技術長的判斷力與持續力都在，junior 的成本與速度也都在。

這個 skill 就是這個團隊。強模型（Opus 5.5+／GPT-6 Astra）當**技術長**：盤點現況、拆工單、定驗收，不寫實作碼——它的每一分額度都花在判斷上。便宜快速的 Flash 級模型當 **junior 工程師**埋頭寫碼。再找另一家廠商的模型做外部唯讀 code review，技術長逐條核實、親自重跑每條驗收命令，逐張提交。

**資深的判斷，junior 的成本**——goal 再大，燒的是 DeepSeek Flash，不是你的 Opus 訂閱。

> A tech-lead skill for coding agents: your strongest model plays the senior tech lead — it inventories the repo, splits the goal into verifiable tickets, dispatches cheap flash-tier juniors to implement, re-runs every acceptance command itself, gets an out-of-family model to review read-only, and commits ticket by ticket. Senior judgment, junior cost.

## 改版思路：先把目標定住，再拆解

第一版的問題不在模型不夠強，而在**一則 session 扛了全部職責**：對齊需求、盤點、派工、等待、驗收、審查、提交都擠在同一段 context 裡，越到後段判斷越糊，session 一斷，派出去的工人和驗收進度也跟著斷。

這一版借鏡 [OpenRig](https://github.com/mvschwarz/openrig) 的兩個想法——**持久的角色**與**明確的交接**——改成兩層：

1. **目標確定，才拆解。** 規格段只做一件事：跟你把「做什麼／不做什麼／怎麼算完成」對齊，寫成確認清單。「不做什麼」寫不出來，就代表範圍還沒定，不開派。定住之後才拆成工單與工單鏈（同一條鏈共用一棵 worktree，互不依賴的鏈才平行）。
2. **判斷歸 skill，執行歸帳本。** 技術長只負責判斷（拆單、驗收、核實、提交）；派工、等待、恢復、交接交給 [Relay](https://github.com/thx0701/osslab-manager/tree/main/relay)（`osrelay`）——一個本機 CLI，用 SQLite 記每張單、每次 attempt 與證據指紋。工人比技術長活得久；技術長換 session 用 `context` 接手，不靠記憶；`accept` 由程式核對：這張單驗過的每一條命令最新一次都成功、最新審查成功（低階單可註明理由豁免），而且都對應目前 Git 版本、證據檔沒被換掉——它不替你判斷命令選得對不對；`finalize` 核對你的提交就是驗收過的那棵樹、HEAD 是這個提交、工作樹與暫存區乾淨、而且是驗收起點的直接單親提交（沒有變更時可沿用原 HEAD）。

於是 session 按職責分段：**規格段 → 施工段 → 驗收段**，每段結束寫約 2KB 的交接，下一段只讀交接開工（見下方「三段式 session」）。

### 要不要搭 Paseo

**不是必須，但建議搭。** 三層分開看：

- **skill**：任何 host 都能用；沒裝 Relay 時技術長用 `scripts/` 的 helper 手動派工。
- **Relay**：任何 Linux 主機裝了 `osrelay`，Claude Code 或 Codex 當技術長就走 Relay（Paseo 上或一般終端機都行）。ZCode／Cursor 也能派工，但 `bind` 只記 codex／claude。
- **Paseo**：只多一件事——自動接段。

搭 [Paseo](https://github.com/getpaseo/paseo) 多得到的是**自動接段**：你下了持續目標（goal、做到完、Codex `/goal`）時，技術長段落結束會用 Paseo 的 `create_agent` 自己開下一段；沒有 Paseo，它會停下來給你一段開頭文字，你開新 session 貼上即可。長工單鏈、會跨好幾段的工作，搭 Paseo 省最多手。

## 給 goal 的三要素

goal 停在技術長這層；往下每一張工單都是帶驗收命令與預期輸出的契約。想讓技術長接得住，把三件事講清楚：

1. **邊界**：什麼不算在內。goal＝授權範圍，沒邊界的 goal 授權過大。
2. **成功訊號**：做完你會觀察到什麼。這是技術長的驗收錨點，你不用自己寫命令。
3. **權威契約**：哪份 spec／文件是決策正本。已定的決策直接沿用，不重問。

例：「把 FB 賣貨便上架補到 spec 完整覆蓋。不含金流與物流。做完每個品項在賣場都看得到對應規格與狀態。正本：`docs/listing-spec.md`。」

未定的業務規則（錢、權限、違約條款…）技術長會一次一題回來問你——那不是摩擦，是管線在擋「AI 發明業務規則」。

操作者一頁說明（誰做什麼、確認清單、三段式換 session、何時用 Relay）：[docs/operator-guide.md](docs/operator-guide.md)。

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
4. （建議）安裝 Relay：`cd relay && python3 deploy/install-user.py`，再照 [relay/docs/paseo.md](https://github.com/thx0701/osslab-manager/blob/main/relay/docs/paseo.md) 啟用 `osrelay.service`。技術長會照 [docs/relay.md](docs/relay.md) 改走 Relay 派工。
5. 在對話裡說「托管」「走工單」「派出去」，丟出帶三要素的 goal，技術長就會照 skill 跑。

## 流程

一個 goal（三要素）→ 盤點（先量再問，缺口表讓你選範圍）→ 決策就緒（已定／觀察／未定三分類，未定的回來問你）→ 拆單（一張一事、`blocked-by` 完整依賴、驗收寫命令與預期輸出、`review-tier` 預估分級）→ 派工（乾淨環境、凍結 helper 可選、死單有收屍流程）→ 技術長驗收（回執只是 junior 的說法，命令自己重跑）→ 異族審查（高階單跑 Grok，低階單跳過）→ 逐條核實（審查員常看錯）→ 逐張本機提交（阻擋級不得拆單繞過；已核實小 nit 技術長可直修）→ push 前整批 code-review → PR。

工單放 `_tickets/open|doing|done/`（目錄即狀態），回執放 `_receipts/`，執行紀錄放 `~/.local/state/osslab-manager/`。

## 三段式 session

技術長按職責分段換 session，不讓一則 session 扛全部：**規格段**（對齊、盤點、拆單、貼確認清單）→ **施工段**（派 junior、收回執）→ **驗收段**（重跑驗收、審查、核實、提交）。每段結束把約 2KB 的交接寫進 `~/.local/state/osslab-manager/handoffs/`，下一段只讀交接開工。低階單可在施工段接著驗收，修復單留在驗收段就地派；段內跑了約 3 小時或 context 約 60% 也會換。你在 Paseo 上已經下了 goal（或 Codex `/goal`）時，技術長自己開下一段；否則它停下，把可貼上的開頭交給你。做法在 SKILL.md「九、按職責分段換 session」。

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

Relay（`relay/`）需要 Linux、Python 3.11+ 與 Git，只用標準函式庫；runner 建議用 systemd user service 常駐。SKILL.md 提到的 `develop → implement → verify-change → code-review`、`to-tickets` 是我們內部的配套 skill 鏈（skill 也寫了沒有時怎麼收斂），外部使用者可換成自己的開發流程；grill／to-spec 等對齊工具同理。金鑰路徑與模型路由改 `scripts/` 開頭幾行即可。

## License

MIT，見 [LICENSE](LICENSE)。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。
