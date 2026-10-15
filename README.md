# OSSLab Manager · 強模型當技術長，Flash 當 junior（Claude Code／Codex）

**中文** | [English](README.en.md)

你想要的是一個**資深技術長帶 junior 工程師**的團隊：技術長的判斷力與持續力都在，junior 的成本與速度也都在。

這個 skill 就是這個團隊。強模型（Claude Opus 5.5+／GPT-6 Astra）當**技術長**：盤點現況、拆工單、定驗收，原則上不寫實作碼（只在收尾剩幾張小單、或審查的小修時自己改）——它的額度幾乎都花在判斷上。便宜快速的 Flash 級模型當 **junior 工程師**埋頭寫碼，卡在範圍或契約衝突時可以在施工中直接問技術長。再找另一家廠商的模型做唯讀 code review，技術長逐條核實、親自重跑每條驗收命令，逐張提交。

**資深的判斷，junior 的成本**——goal 再大，燒的是 DeepSeek Flash，不是你的 Opus 訂閱。

> A tech-lead skill for Claude Code and Codex: your strongest model plays the senior tech lead — it inventories the repo, splits the goal into verifiable tickets, dispatches cheap flash-tier juniors to implement, answers their questions mid-task, re-runs every acceptance command itself, gets an out-of-family model to review read-only, and commits ticket by ticket. Senior judgment, junior cost.

## 支援範圍

| 角色 | 支援 | 備註 |
|---|---|---|
| 技術長（經理） | **Claude Code**、**Codex** | 只支援這兩種。Claude 用 Opus 5.5 以上、思考 high 以上；Codex 用 GPT-6 Astra、固定 **medium**（實測每步比 xhigh 快約 3 倍） |
| junior（預設） | pi CLI 無頭＋**DeepSeek v4.1 Flash**，走 **RunInfra**（按量計費；不是 OpenRouter，也不是 DeepSeek 官方 API，見下方說明） | `scripts/pi-runinfra-worker.sh` |
| junior（同模型，指定時） | 同上，改走 OpenRouter | 不在自動退路裡，使用者指定才用 `scripts/pi-openrouter-worker.sh` |
| junior（備援） | ZCode CLI＋GLM-5.3-Flash（BigModel Coding Plan） | DeepSeek 驗收不過且像是模型能力時；`scripts/zcode-cloud-worker.sh` |
| junior（指定才派） | Claude Code 無頭＋claude-haiku-5-5（本機訂閱） | 只手動派工，不進 Relay；`scripts/claude-haiku-worker.sh` |
| 外部審查 | 依序 **Codex** GPT-6 Astra medium → **GLM-5.3** max → **Grok 4.7** medium（已停訂），都可指定 | 唯讀：Codex 走唯讀沙箱，GLM、Grok 只給 Read／Grep；`scripts/codex-readonly-review.sh`、`scripts/zcode-readonly-review.sh`、`scripts/grok-readonly-review.sh` |

Cursor、ZCode 不當技術長：等待、交接與施工中問答都只在 Claude Code、Codex 上驗過。

> **DeepSeek 的來源很關鍵**：我們用的是 [RunInfra](https://runinfra.ai) 的 `deepseek-v4-1-flash` 端點。RunInfra 是針對 agent 工作負載優化的託管服務，同一個 session 的重複呼叫會送到已有快取的副本（官方宣稱快取命中 92～99% 以上）。2026-10-04 單輪對照，同一顆模型的工具第一跳與 OpenRouter 相近或略快、長輸出約快 4～5 倍，所以改為預設，OpenRouter 保留為退路。本 README 的速度與費用數字都來自 RunInfra，換成 OpenRouter 或 DeepSeek 官方 API 要重新量。

## 怎麼運作

一個 goal → **盤點**（先量再問，缺口表讓你選範圍）→ **決策就緒**（已定／觀察／未定，未定的回來問你）→ **拆單**（一張一事、`blocked-by` 依賴、驗收寫成命令與預期輸出）→ **派工**（乾淨環境、凍結 helper）→ **技術長驗收**（回執只是 junior 的說法，命令自己重跑）→ **異族審查** → **逐條核實** → **逐張本機提交** → push 前整批 code-review → PR。

**判斷歸 skill，執行歸帳本。** 派工、等待、恢復、交接交給 [Relay](https://github.com/thx0701/osslab-manager/tree/main/relay)（`osrelay`）：一個本機 CLI，用 SQLite 記每張單、每次 attempt、每個問答與證據指紋。junior 比技術長活得久，技術長換 session 用 `context` 接手，不靠記憶。`accept` 由程式核對每條驗證命令最新一次都在目前 Git 版本通過、審查成功、證據檔沒被換掉；`finalize` 核對你的提交就是驗收過的那棵樹。

這一版新增的兩件事：

- **即時進度**：junior 每個工具起訖、每則模型回覆、每次重試都即時寫一行進 log（`bash: npm test`、`bash 完成 20.0s`）。Relay 的 900 秒靜默警報因此只在真的卡住時響，響的時候 log 最後一行就是卡在哪個命令。
- **施工中問技術長**：junior 碰到「工單只准改 A 檔，但驗收也要改 B 檔」這類範圍或契約衝突時，呼叫 `ask_manager` 發問並暫停（固定四欄：卡在哪、選項、建議、不回答的影響；每輪最多 3 題）。技術長的 `osrelay wait` 以退出碼 5 收到題目，`osrelay answer` 回覆後 junior 在同一輪接著做；12 分鐘沒回就照原規則停下受影響的部分、寫進回執。回答視為工單補充，驗收與審查都把它算進允許範圍。

## 近期更新（2026-10）

- **Relay 叫醒技術長**：attempt 結束或 junior 發問時，Relay 經 Paseo 的 steer 送一則固定格式的通知給該 owner 最近 `bind` 的 session（Codex 預設開、Claude 預設關；`bind --wake on|off`）。steer 不打斷進行中的指令，會提前結束 Codex 的原生 `sleep`。通知只列 id、狀態與期限，不含 junior 寫的文字。
- **Codex 技術長改用 5 分鐘 sleep**：原生 `sleep` 5 分鐘，醒來用 `osrelay wait --owner <owner> --timeout 0` 一次查完同 owner 所有鏈；有事件時叫醒會提前結束 sleep，叫醒壞了 sleep 仍保底。起因是 1 秒 yield 輪詢讓等待佔了 token 四到五成。
- **`osrelay wait --owner`**：一次看同 owner 所有 attempt，回報還沒回報過的結束、待答題目、靜默與叫醒失敗；退出碼同單一 `wait`，另有 `idle: true` 表示沒有進行中的工作。
- **收尾模式**：剩不超過 3 張小單，或上線後使用者在旁實測的調整期，技術長說一聲「剩 N 項，改我自己做」就自己改；修前補驗、驗收重跑、外部審查與逐張提交照舊，秘密、權限、錢與對外契約仍走 junior。
- **SKILL 瘦身與接手最小讀取**：SKILL.md 從約 44KB 減到約 22KB，只留會影響「下一步准不准做」的規則，細節移到 `docs/`（workers、discovery、tickets、acceptance、review、remediation、closeout），做那個動作前才讀。換 session 時後繼只讀交接檔與該段要用的章節，長 notes 只查需要的段落；context 到 50% 先寫交接、60% 不再開新一輪。
- **審查收斂與單一驗收入口**：第 2 輪起只剩 minor 由技術長直修；P1 修 3 輪未收斂改派更強施工者或技術長收尾，不再派 Flash。多項驗收寫成清單，用 skill 的 `scripts/acceptance-run.sh` 跑成一條 verify；驗收工具每條鏈最多一張單，之後工具問題由技術長直修、只做 code-review。
- **junior 遵循 YAGNI**：工人 prompt（`templates/worker-prompt.md`，pi、ZCode、Haiku 共用）要求只做工單要求的事，優先最小、最直接的解法（一行能解決就不寫十行），不加工單沒要求的抽象、選項、相容層或防禦碼；但不為了縮短犧牲可讀性、錯誤處理或驗收。這條只給 junior，技術長不受限。
- **pi junior 改走 RPC 驅動程式**：`scripts/pi-worker-driver.py` 以 `pi --mode rpc` 啟動 pi，取代原本整輪結束才輸出的 `-p` 文字模式。驅動程式負責即時進度、轉接發問，並照文字模式判斷成敗（模型出錯時 pi 自己仍回 0，驅動程式改回 exit 1）；訊號轉送、父程序死掉 pi 跟著收尾、Relay 的 worktree 鎖都照舊。
- **`osrelay wait` 退出碼一覽**：0 查詢成功（成敗仍看 `result.status`）、3 等候逾時（工作照跑）、4 日誌靜默 900 秒、5 有題待答。4 與 5 都只通知一次：4 是同一組日誌大小只報一次，5 是每一題只報一次；例外是已經在跑的 `wait` 會回報它開始後才問的題（就算背景等待已報過），技術長前景等審查時也接得到別條鏈的發問。5 先於其他結果回報。
- **讀題與回答**：`osrelay questions --owner <owner>` 列出待答題目全文，`osrelay answer <attempt> --qid <qid> --owner <owner> --text …` 回覆。每題只通知一次（已經在跑的 `wait` 例外，見上一條），技術長不想答就讓它 12 分鐘後逾時，之後才開始的 `wait` 不會再被同一題叫醒。
- **回執新增「## 5. 問答」**：junior 逐題列出題目、技術長的回覆（或「沒有經理通道」「沒有收到經理回覆」）、照回覆做了什麼。已答的題目寫在這裡，不放第 4 節「風險與存疑」，免得擋住下一輪 `--resume`。
- **「無。」不再擋接續**：Relay 判斷回執第 4 節有沒有存疑時，「無」加一個清單符號或結尾句號（「無。」「- 無」）都算沒有存疑；「無。但 X 未驗」或多列一條仍算存疑。
- **驗收要在起點失敗**：會改變行為的工單，至少一條驗收命令要在起點 commit 失敗，而且是因為這張單要改的行為；技術長派單前先跑一次寫進工單，起點就會過的命令只算回歸保護。靠 junior 新寫的測試才分辨得出時，驗收時把新測試放回起點版本補驗。起因是實測發現有一張單的驗收在起點就會過，重跑也擋不住。

## 快速開始

1. 把本 repo 放到 `~/.agents/skills/osslab-manager/`（Codex 直接掃這裡；Claude Code 用 symlink 掛同一份）。
2. 準備 secret 檔（金鑰只走環境變數，不進 argv／log／git；路徑可改 `scripts/` 開頭幾行）：
   - `~/.openclaw/secrets/glm-5.3-flash.env`：`GLM_53_FLASH_API_KEY=...`（RunInfra，預設 junior）
   - `~/.openclaw/secrets/openrouter.env`：`OPENROUTER_API_KEY=...`（OpenRouter 退路）
   - `~/.openclaw/secrets/glm-coding-plan.env`：`ZHIPU_API_KEY=...`（GLM 備援與 GLM 審查）
3. 本機需要 `pi`（0.99 以上，RPC 模式）、`python3`；審查用 `codex`（ChatGPT 登入），選用 `grok`；GLM 備援與審查用 `zcode`（路徑可用 `ZCODE_CLI_BIN` 覆蓋）。
4. 安裝 Relay：`cd relay && python3 deploy/install-user.py`，再照 [relay/docs/paseo.md](https://github.com/thx0701/osslab-manager/blob/main/relay/docs/paseo.md) 啟用 `osrelay.service`。施工中問答只在 Relay 派工時有；沒裝 Relay 時技術長照 `docs/manual-dispatch.md` 手動派工，junior 發問會立刻得到「沒有經理通道」。
5. 在 Claude Code 或 Codex 對話裡說「托管」「走工單」「派出去」，丟出帶三要素的 goal。

## 給 goal 的三要素

1. **邊界**：什麼不算在內。goal＝授權範圍，沒邊界的 goal 授權過大。
2. **成功訊號**：做完你會觀察到什麼。這是技術長的驗收錨點，你不用自己寫命令。
3. **權威契約**：哪份 spec／文件是決策正本。已定的決策直接沿用，不重問。

例：「把 FB 賣貨便上架補到 spec 完整覆蓋。不含金流與物流。做完每個品項在賣場都看得到對應規格與狀態。正本：`docs/listing-spec.md`。」

未定的業務規則（錢、權限、違約條款…）技術長會整理成一輪題目回來問你（每題附建議）——那不是摩擦，是管線在擋「AI 發明業務規則」。操作者一頁說明：[docs/operator-guide.md](docs/operator-guide.md)。

## 實測

- **速度與規模**：2026-09-28～10-10 經 Relay 派出 167 次 pi junior，中位數 8 分鐘完成、九成在 25 分鐘內；一個 Codex（GPT-6 Astra）技術長 session 連續 14 小時派了 80 張單。
- **靜默警報從假變真**：改成即時進度前，上面那個技術長 session 收到 20 次靜默警報，20 張單最後都正常完成，全是誤報；以 pi session 時間戳回放，改版後這批預測 0 次誤報，全機 43 張長單只剩 2 張會響——都是 junior 對整顆磁碟跑 `find /`、`grep -r` 18 分鐘的真異常。
- **施工中問答**：真機冒煙時 junior 以「契約衝突」發問、附證據與三個選項，技術長回答後 15 秒內收到並完成，回執逐題記下問答。
- **正確性比單開發精準**：每張票都要過「驗收命令重跑＋異族審查＋逐條核實」三層檢查；同一個模型寫完自己看，盲點一模一樣。
- **代價只有時間**：一張中型票從派單到三輪審查結束約 1.5 小時，急件不適合。
- **工人對照（2026-10-11）**：DeepSeek（RunInfra）對 Claude Haiku 5.5，三張真實工單、三輪：DeepSeek 9/9 成功、快 1.5～1.7 倍；Haiku 走 Pro 訂閱每張單約用掉 5 小時額度 1～2%。完整報告：[docs/benchmarks/2026-10-11-deepseek-vs-haiku.md](docs/benchmarks/2026-10-11-deepseek-vs-haiku.md)。

### 案例：browser-workflow（瀏覽器租用與人工接手）

28 個檔、+5,091 行；4 張工單（T1 加 3 張修復單）、3 輪 Grok 審查，約 1.5 小時，最後 60 個測試全過、合成一個 commit。junior 自己寫的 57 個測試全綠，但第一輪審查找出 8 條成立的問題（續租會卡住、父程序結束後留下孫程序）；第二輪再抓到正式 wrapper 可被繞過、讀寫格式不一致導致重啟後 state 損毀；第三輪零問題才提交。這些都是「測試全綠但實際有錯」的缺陷。

## 三段式 session

技術長按職責分段換 session：**規格段**（對齊、盤點、拆單、貼確認清單）→ **施工段**（派 junior、收回執、回答發問）→ **驗收段**（重跑驗收、審查、核實、提交）。每段結束寫約 2KB 的交接到 `~/.local/state/osslab-manager/handoffs/`，下一段只讀交接開工；段內跑約 3 小時或 context 約 60% 也會換。做法在 SKILL.md 第九節。

### 選配：Paseo 自動接段

不裝 [Paseo](https://github.com/getpaseo/paseo) 也能完整運作，Relay 不依賴它。裝了之後，你下了持續目標（goal、Codex `/goal`）時，技術長會在段落結束時用 Paseo 的 `create_agent` 自己開下一段，我們的環境實際用它接段。

## 什麼時候不要用

- 小修一行、改個文案——直接做，別付拆單成本。
- 探索型 spike：連「做完長什麼樣」都說不清楚，寫不出驗收。
- 決策密集的工作：每張單都要人拍板，技術長只是傳聲筒——先談清楚再進管線。

## 安全邊界

- junior 以**乾淨環境**啟動，不繼承技術長 session 的 token 與業務憑證；pi junior 另以精簡模式啟動，不載入 skill、其他擴充與任何一層 AGENTS.md，repo 自己的規矩由指示要求它讀。
- 施工中問答的答案只經 pi 的 RPC stdin 送回；寫入端不會漏給 junior，Relay 通道變數也不傳給 pi，junior 無法自己回答自己。不可逆操作、正式站與秘密一律不准問，技術長回答了也照舊禁止。
- 審查員**唯讀**（Read／Grep），不得改檔。
- 施工只准 helper CLI；宿主 subagent（Claude Agent／Task、Codex subagent）一律禁用——它們跑在技術長進程裡，繞過整個隔離設計。
- 隔離是同一使用者下的操作契約，不是權限沙箱：junior 仍在本機跑 shell。工單不寫秘密，碰正式站的驗證由技術長自己做。

## 與 upstream（yanauto/opus-manager）的差異

- 工人路由預先定好：DeepSeek（RunInfra）預設，不能用就改 GLM-5.3-Flash 備援（OpenRouter 只在指定時），唯讀審查依序 Codex → GLM → Grok；Claude Haiku 只在指定時手動派工
- Relay 帳本：派工、等待、恢復、交接、驗收與提交核對都有程式化的證據指紋
- 即時進度與施工中問答（pi RPC 驅動程式＋`ask_manager` 擴充）
- 先量再問：盤點產出缺口表，人選範圍；拆單「人管範圍、技術長管粒度」
- 工單有 `blocked-by` 依賴；不同 worktree 平行跑不同鏈
- 審查分級（`review-tier`）：動到斷言／guard／錢權類一律高階，只升不降
- 技術長直修：已核實的非阻擋小 nit 可直接改；阻擋級照舊走 junior（收尾模式例外）
- 收尾模式：剩 3 張以內的小單或上線後調整期，技術長自己改，閘門照舊
- Relay 叫醒：attempt 結束或發問時經 Paseo steer 叫醒技術長，Codex 用 5 分鐘 sleep 保底
- 死單回收：PID 重用檢查、半套改動先備份、重派記在同一張單
- 三段式 session 與 2KB 交接
- 團隊時間戳用台灣時間（+0800）

## 環境假設

Relay 需要 Linux、Python 3.11+ 與 Git，只用標準函式庫；runner 建議用 systemd user service 常駐。SKILL.md 提到的 `develop → implement → verify-change → code-review`、`to-tickets` 是我們內部的配套 skill 鏈，外部使用者可換成自己的開發流程。金鑰路徑與模型路由改 `scripts/` 開頭幾行即可。

## 路線圖

- 支援其他時區（目前寫死台灣時間 UTC+8）。
- 補測做法對照（接續[工人實測](docs/benchmarks/2026-10-11-deepseek-vs-haiku.md)，GLM-5.3 High 交叉審查後的清單）：
  - **全流程成本與時間**：A（Opus 經理＋DeepSeek）、B（Opus 經理＋Haiku）連同經理寫單、等待、重跑驗收、外部審查的時間、token 與訂閱額度；C（Opus 5.5 自己寫）effort low、medium 各跑一次；D（Haiku＋Opus 顧問，Claude Code `--advisor`，先確認訂閱下能用）並記實際諮詢次數。
  - **品質**：拿當時驗收過的最終測試當標準答案比較；起點就會過的驗收先剔除。
  - **取樣偏差與長尾**：補幾張當時 DeepSeek 沒一次做完的單；每種做法記最慢那幾次（p95），不只看中位數。

## License

MIT，見 [LICENSE](LICENSE)。改編自 [yanauto/opus-manager](https://github.com/yanauto/opus-manager)（MIT）。
