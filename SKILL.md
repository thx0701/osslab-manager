---
name: osslab-manager
description: >-
  工單托管：經理（Claude／ZCode／Codex／Cursor）不寫實作，先盤點現況，再把開發拆成工單，
  預設派給 pi（本機執行、模型 DeepSeek v4.1 Flash 走 OpenRouter）施工、ZCode（GLM-5.3-Flash，
  Coding Plan）為備援，交 Grok Build（grok-4.7，medium）唯讀異族審查，經理負責驗收、
  逐條核實與逐張本機提交。
  觸發：走工單、托管、派出去、派給別的模型做、osslab-manager、manager skill、opus-manager（舊名）。
  平時照常自己動手，只在使用者要求時使用。
scope: company
tags: [all]
runtimes: [claude, zcode, codex, cursor]
notes: >-
  改編自 yanauto/opus-manager（MIT），舊名 opus-manager。公開副本是 https://github.com/thx0701/osslab-manager ；
  helper 用 $HOME 與 ZCODE_CLI_BIN，不寫死家目錄。Cursor 個人目錄不得另放 opus-manager 實體，改掛同一份 `~/.agents/skills/osslab-manager/`。
---

# 工單托管（OSSLab manager）

只在使用者要求托管時使用。經理是目前這則 session 的 bot（Claude、ZCode、Codex 或 Cursor），負責盤點、拆單、派單、驗收、核實與提交；人決定未定的業務規則。實作交給工人，經理不親自寫實作碼（驗收不過時也不偷偷修，開跟進單；例外只有第二節的經理驗收工具與第六節的經理直修）。四種經理都在背景派工與派審查、照第三節第 4 點的等法等完才收，不留未等待的調用、不用 nohup／`&` 脫離。施工只准本 skill 的 helper CLI（見「規矩」）。skill 檔與 scripts 走共用掛載 `~/.agents/skills/osslab-manager/`：Codex、ZCode 直接掃 `~/.agents/skills`，Claude Code 的 view 與 Cursor 個人目錄是指向同一實體的 symlink。**Codex 經理在 Paseo 要用 Full Access（`auto-review` 模式網路受限，派工一定會被擋），推理固定 medium，goal 裡也不升 xhigh。**

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 施工（預設） | pi CLI 在本機以 `-p` 無頭模式執行；模型 `deepseek/deepseek-v4.1-flash` 走 OpenRouter（按量計費，思考 `high`）；精簡啟動，不載入 skill、上層 AGENTS.md 與擴充 | `scripts/pi-openrouter-worker.sh [--resume <接續鍵>] <workdir> <ticket>` |
| 施工（備援） | ZCode CLI 在本機以 yolo 模式執行；模型 `GLM-5.3-Flash` 走雲端（BigModel Coding Plan 訂閱，思考預設 Max） | `scripts/zcode-cloud-worker.sh [--resume <接續鍵>] <workdir> <ticket>`（不接續，一律從零） |
| 審查 | Grok Build，`grok-4.7`，reasoning effort `medium`，只給 Read／Grep | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |
| 等待（工具） | 阻塞到 pid 結束，只印一行 | `scripts/wait-worker.sh <pid\|worker.log\|review.err> <max_seconds>` |
| 收屍備份（工具） | 保存 binary patch 與未追蹤檔，核對後才准人工清理 | `scripts/backup-worktree.sh <workdir> <全新備份目錄>` |
| 證據（工具） | 跑一條命令，完整輸出與 JSON 信封存檔，stdout 只印摘要 | `scripts/evidence-run.sh <out-dir> <label> -- <命令…>` |

路由已由本安裝定好，不重新摸工人、不另寫 `workers.md`。helper 不用本機自架模型 provider；憑證只從既有 secret 檔載入（`openrouter.env`、`glm-coding-plan.env`），不進 argv／log／git。要換模型或工具先問人，再改本 skill 開 PR。

**選工人**：預設 DeepSeek（2026-09-27 同票對照：小票約 7 倍快、中票略快，品質與誠實度相當）。遇到下列情況改派 GLM 備援，並在 `claimed-by` 寫實際引擎：DeepSeek 啟動失敗、API 錯誤、額度或速率限制；同一張單 DeepSeek 驗收不過且原因像是模型能力；使用者指定。
經理為 ZCode 時，備援工人與經理同屬 BigModel 系，且備援與本機 session 共用 Coding Plan 額度、可能互卡速率——預設仍 DeepSeek，異族審查照舊是 Grok；這種情況下改派備援等於換自己人施工，`claimed-by` 照實寫。
兩者的程式碼與工單內容都會送到各自的雲端模型供應商（OpenRouter／DeepSeek、BigModel），工單照舊不寫秘密。

**工人隔離的邊界**：helper 以乾淨環境變數啟動工人，不繼承經理 session 已匯出的 token 與業務憑證；但工人仍在本機跑 shell，看得到 Docker、網路與磁碟上的檔案（含 secret 檔），「不動 prod」只靠指示。pi 工人另以精簡模式啟動：不載入全域與公司 skill（含通訊與業務系統的）、擴充與 prompt 範本，每一層的 AGENTS.md／CLAUDE.md 都不自動載入（上層共用規矩可能寫著怎麼載入團隊秘密）；repo 自己的 AGENTS.md／CLAUDE.md 改由 helper 指示與工單要求它用 read 去讀，實測會照讀照做。repo 自己的規矩若本身含上層共用段落，工人讀檔時仍會看到，這由指示「不讀取、不輸出秘密」擋。2026-09-27 實測每次請求的 prompt 從約 7.3k token 降到 1.6k，工具照舊 read／bash／edit／write。zcode 備援還沒有對應的精簡開關，照舊載入。所以工單不寫秘密或 secret 路徑；凡要碰 prod 的驗證（唯讀煙霧、XML-RPC、瀏覽器）由經理在第四節自己做；給工人拋棄式測試環境，並寫明哪些共用資源不准刪。

OSSLab 開發順序照舊：`develop → implement → verify-change → code-review`；Grok 審查是 code-review 內的獨立意見，不取代它。本文提到的 `grill-with-docs`、`grill-me`、`to-spec`、`to-tickets`、`verify-change`、`code-review` 是配套 skill；host 沒有時，改用工單的驗收命令與預期輸出、第四～六節的重跑與核實收斂，閘門不因缺 skill 而省略。工人不 commit、不 push、不動 prod、不挪工單。可行時給工人獨立 git worktree；不把工人派進別人正在用的髒 checkout。

## Relay 執行路徑（Codex／Claude Code 經理）

已安裝 `osrelay` 的主機（Paseo 上或一般終端機皆可），Codex 或 Claude Code 當經理時，托管先讀 [docs/relay.md](docs/relay.md)，由 Relay 保管派工、等待、恢復與交接；本 skill 仍負責決策、驗收與提交。模型與 helper 不變。Relay 程式不喚醒、不開經理 session；自動開下一段只有 Paseo 的 `create_agent`（第九節、`docs/handoff.md`）。

Relay 路徑的 SQLite 是執行狀態正本；下文目錄搬移、手動 PID 等待、收屍與換段程序改用該文件的 CLI 操作，不混用兩套派工。其餘工單品質、依賴、核實與權限規則照舊。未安裝 Relay 的 host 仍用下文原流程；已存在 Relay 任務而 runner 不可用時先恢復 runner，不另走 helper 重派。

## 〇、現況盤點（先量再問）

使用者問「完工了嗎」「做到哪了」「幫我補完」，或經理還不清楚系統現況時，先盤點再拆單。拿著交接檔接手的 session 看交接檔就算清楚現況（第九節；接手信任規則在 `docs/handoff.md`），不因接手重盤。盤點是經理自己的活，不派工人。

1. **完成度正本**：找規格的狀態表、較新的 handoff spec（常取代舊裁決）、各 feature spec 的狀態行，再對照程式與 `git log`。文件常落後程式（做完了仍寫待實作），也可能超前；兩邊不一致就是文件漂移，記進缺口表。
2. **跑所有既有測試層並對帳**：框架實際跑了幾個 vs 檔案裡定義幾個，連案例身分一起核——全綠但沒選中該驗的新場景不算通過。沒註冊進框架的、要直接執行的獨立腳本、被環境卡住的，都找出來另外跑。環境卡住（例如 PDF 渲染自鎖）先處理環境，不要把環境問題當產品缺陷。
3. **唯讀查 prod**（在授權範圍內）：部署版本或 deploy tag 是否等於 master、執行期事實（最後同步時間、排程、系統參數、實際寄件人等）。
4. **每個紅燈分類**，附 commit 時序證據：
   - 產品缺陷；
   - 測試過時（產品後來改、測試沒跟上——看兩邊最後修改的 commit）；
   - 環境問題（缺欄位、缺參數、測試基礎設施）；
   - 規則未定或契約互相矛盾（回第一節）。
5. **缺口表**：已完成／部分完成／缺／待人決定，每列附命令與原樣輸出，交使用者選範圍。先量再問，不要在量之前問「要做什麼」。

盤點建的臨時環境（拋棄式 DB、容器、網路）記下名稱，後續工單直接引用；整批工作收尾時再清。

## 一、派單前：決策就緒

先讀專案規矩（`AGENTS.md`／`CLAUDE.md`）、相關程式與測試。每個新增或改變的驗收結果，在工單寫明決策來源：某版文件章節、已核准的 issue／PR，或使用者明確指示。

- **已定**：契約或使用者已決定 → 直接沿用，不重問。錢、庫存、權限也一樣；風險只決定驗證深度，營運核准規則照舊。
- **觀察**：程式、prod 現象或測試顯示的現況 → 標為現況證據；測試通過或 AI 寫的 spec 不等於人的意圖，不能拿來授權新業務行為。
- **未定**：新業務規則、影響結果的歧義、契約互相矛盾 → 先讀證據，只問剩下的決定。一次一題、附建議與具體例子；要留在 repo 用 `grill-with-docs`，只討論用 `grill-me`，成契約用 `to-spec`。沉默不算同意。

派單條件：驗收可觀察、決策來源可追、失敗／邊界行為寫到、沒有未定的業務或架構選擇。

## 二、寫工單

照 `templates/ticket.md` 寫到作業目錄 `_tickets/open/T<編號>-<短名>.md`：

- 一張單只做一件事；幾條命令說不清驗收就拆開。反過來，同一原因、同一批檔案的小幅對齊（例如數個過時斷言）合成一張單——判準是一組驗收命令證明得了、一次審查看得完。
- 驗收寫命令與預期輸出，並寫「為什麼這樣驗收」——防止測試沒斷言卻過關。
- 驗收命令優先引用 repo 既有的測試腳本；環境陷阱寫進腳本或盤點筆記，不要每張單複製長命令。同一串命令要寫第三次時，先開一張單把它做成腳本。
- 工單引用的工具或腳本必須是**已提交**的版本：派單前確認它沒有未提交修改，也沒有進行中的工單正在改它（含其他 worktree 的路徑）。做不到就等改它的那張單提交後再派，或在工單寫明用 `git show <commit>:<path>` 取出的固定版本。
- **經理驗收工具**：經理為驗收寫的量測、探針、overlay、聚合腳本，派單前先提交進 repo（放 `tests/` 或 `tools/`，單獨一個 commit，body 寫「經理驗收工具」），工單驗收直接呼叫它，工人跑同一支；不要留在 `~/.local/state/`，那裡工人拿不到，只能拿自製小資料自測全過。經理能提交的只有驗收腳本、輸出 schema 與 fixture；產品碼、既有斷言照舊走工人。這些 commit 落在第八節整批 `code-review` 範圍內。
- 邊界寫明：只准動哪些檔、決策來源、回執路徑 `_receipts/<工單名>.receipt.md`、哪些共用資源不准刪。
- 寫兩張派一張；下一張常取決於上一張回執的存疑項。
- 每張在 `blocked-by` 寫前置工單，沒有寫「無」。前置單要在本 worktree 的 base 已有它的 commit 才算解除；它在別的 worktree 提交的，先 rebase 或 merge 進來再派。目錄就是狀態（`open`／`doing`／`done`），不另加狀態欄。
- 需求已走過 `to-tickets`：沿用它的切法與依賴，把票改寫進本 skill 模板——依賴寫進 `blocked-by`，`Verification` 當驗收起點，補到命令與預期輸出才派；`Status` 欄丟掉（目錄就是狀態），補上邊界、回執路徑等欄位。一組驗收命令說不清的票再拆，子單的 `blocked-by` 標回原單。

**拆單要不要人核**：人管範圍，經理管粒度。

- 範圍只核一次：盤點缺口表或使用者原始指示選定的範圍就是授權範圍，不重問。
- 粒度不等人核：派第一張前貼**確認清單**給使用者看，貼完直接開派（沉默不必等「好」，但也不當成新的授權）：
  1. 做什麼：這批的目標一句話；
  2. 不做什麼：授權範圍外、看起來相關但這批不碰的東西，至少一條；
  3. 怎麼算完成：使用者看得到的完成訊號，對應到哪幾條驗收命令；
  4. 拆單清單：Title／chain／git worktree／blocked-by／驗收命令。同一條鏈共用一棵 git worktree，施工與驗收交替。`blocked-by` 為「無」且檔案不重疊的，各開一棵 worktree，才准同時派。
  「不做什麼」寫不出來，代表範圍還沒對齊，回第一節問人，不開派。後面的單正文可以晚點寫細，確認清單仍要有 Title、chain、git worktree、blocked-by；驗收命令照舊寫兩張派一張，沒寫清的不派。使用者插話照「規矩」判斷。每張工單 header 寫 `chain` 與 `git-worktree`，跟進單沿用母鏈名。
- 只在這三種情況停下等人：拆單超出授權範圍（順手改別的模組、多修一個 bug）；要決定分開 PR 或分批部署；遇到未定的業務規則（回第一節）。
- 範圍內的跟進單、修復單、切太大拆出的子單都不再問。

## 三、派單

1. `mv` 到 `_tickets/doing/`（挪成功＝上鎖），派出後由經理照 `worker.log` 起跑行的 `engine=` 與 `at=` 填 `claimed-by`（`引擎 @ 時間`），不自己抄模型名；helper 的 `at=` 已是台灣時間，主機時鐘是 UTC，別用裸 `date`。
2. 背景執行 helper（一張單常跑一分鐘到數十分鐘）。派工指令、attempt 目錄、`helper exit=<n>` 收尾行、`--resume <接續鍵>` 何時可帶、凍結 skill 副本的做法：照 [docs/manual-dispatch.md](docs/manual-dispatch.md) 第 1 節，不自己改寫指令。
3. 同一個 worktree 一次只派一張；不同 worktree 可以平行跑不同工單鏈。只派 `blocked-by` 已解除的單。一條鏈的 review 要等該 worktree 沒有進行中的工人或 verify；這時另一條鏈可以在自己的 worktree 上施工。
4. **一次等到底**：等待中不跑 `ps`、`git status`、不看 log，也不用 10 秒以下的輪詢——每次探詢都是一整輪經理推理，外加重送整個 context。完成信號依 host 而定，審查員與長測試也照這樣派、照這樣等：
   - Claude Code、ZCode：背景執行，等 host 的完成通知（ZCode 的背景 Bash 結束會主動回報，2026-09-28 本 skill 的 Grok 審查派工即以此收工；wait-worker.sh 只作 fallback）。
   - Codex：受管 session（`exec_command`／`write_stdin`）加 code-mode 迴圈等 `exit_code`，具體做法與 JS 範例見 `docs/waiting.md`。
   - Cursor 或任何沒有確認過完成通知的 host：背景派工後，前景跑 `wait-worker.sh <worker.log|review.err> <max_seconds>`（工人等 `worker.log`、同 session 的審查員等 `review.err`；只靠 bash 與 `/proc`；`max_seconds` 設得比該 host 單次命令逾時短，回 124＝還在跑，再跑一次）。
   - 等的不是本 session 起的進程（例如換 session 後）：前景跑 `wait-worker.sh`，參數給 log 或 pid（工人 `worker.log`、審查員 `review.err`；輸出行與 exit code 語意見 script 標頭註解，只認 log 最後一行的 `helper exit=<n>`，helper 記的 `proc_start` 會擋 PID 重用誤判）。
   - 等到逾時才允許一次診斷（pid、log 尾），然後繼續等，或照第 7 點收屍；不要為了看進度去 kill 或重派。
   - 使用者插話會打斷等待。回應完，只要還有進行中的工人、審查員或長測試，就立刻照上面的等法回去等，不結束這一輪；Relay 不會喚醒經理，這一輪一結束，完成的工人就沒人收。
5. 等到第 4 點的完成信號再讀回執；讀到回執前不轉述、不猜結果。helper 非零退出時，即使有回執也要先查再收。
6. 改派單指示時，連 helper 實際送出的 prompt 一起看。擷取到的呼叫只證明送了什麼，不證明模型照做。
7. **卡在 `doing` 的單怎麼收**（helper 非零退出、工人死在半路、重派次數與收屍順序）：照 [docs/manual-dispatch.md](docs/manual-dispatch.md) 第 2 節。收屍完成前，不在這個 worktree 疊任何 `T<編號>b` 或下一張單。

工人若遇到未定的業務決策或契約衝突，應停下並在回執回報證據；經理回到第一節處理後再重派。

## 四、驗收（經理自己來）

回執是工人的說法，不是證據。

1. 讀回執與實際 `git status`／`git diff HEAD`（含 staged、untracked），確認只動了允許的檔、沒刪改不該動的；並照實際 diff 重定 `review-tier`（見第五節）。
2. 工人結束後，每條驗收命令自己重跑，和回執對照；有 API 就實際打一次，需要 prod 的驗證也在這裡由經理做。重跑範圍就是工單列出的命令：每張單的 `verify-change` 跑工單命令與受影響的 targeted 測試，不含全量；全量（多片、manifest、hash 對帳）整批只在第八節收尾跑一次，不為單張驗收重組全量或複製 runner。
3. 讀存疑項並處理。
4. 不過：契約已定 → 寫跟進單 `T<編號>b` 再派；預期結果未定 → 回第一節。

輸出很長的驗收命令用 `scripts/evidence-run.sh <out-dir> <label> -- <命令…>` 包起來：完整 log 與 JSON 信封（cwd、命令、命令 exit、wrapper exit、起訖時間、執行前後的 HEAD／diff／untracked 指紋）存到工單狀態目錄（[docs/manual-dispatch.md](docs/manual-dispatch.md) 第 1 節的 `$D`），同名不覆蓋。只有 wrapper exit=0、JSON 存在且 `verification_status=passed` 才算通過；證據失敗或執行前後指紋不同不得驗收。版本變動先查原因，固定受驗版本後重跑；被 ignore 的檔、submodule 內部內容與外部環境不在指紋範圍。schema 2 保留原頂層版本欄位作為結束快照，完整版本在 `before`／`after`。通過時對話與審查包只引用 JSON 路徑和 exit code，失敗才讀它印的最後 20 行——通過的長 log 讀進對話，之後每一步都要重送。同一串命令寫到第三次、或驗收本身是多片全量時才用；短命令照舊直接跑。分片、manifest 這類跑法仍是各 repo 自己的 runner。

最後一次實作變更後跑 `verify-change`。驗收過了還不提交，先走第五、六節審查，提交在第七節。

## 五、Grok 異族審查

**審查分級**：`review-tier` 寫在工單 header，派單時先預估。

- **高階（Grok＋`code-review`）**：碰到錢、權限、庫存、對帳、migration、對外契約或憑證設定的單；或任何動到斷言、guard、skip、驗收命令本身的單——就算它屬於「測試對齊」也一樣，這些改動改的是「通過的意義」。
- **低階（只 `code-review`，跳過本節）**：純文件、命名、格式、不動斷言的測試對齊。
- 預估只是預估：第四節照實際 diff 重定，碰到上列任一項就升高階；只升不降，拿不準算高階。
- 第八節 push 前的整批 `code-review` 不分級，一律照走。

準備審查包：工單與決策來源、回執、完整 diff（凍結成檔：`git diff HEAD`；新增檔先 `git add -N` 才會出現在 diff 裡）、repo 根與固定點 SHA、驗證證據（精確命令、工作目錄、exit code、原始輸出，對應受審版本；豁免要寫理由與未驗範圍）。「測試都過了」這種摘要不算證據。

把審查提示寫進檔案後，一律背景執行，照第三節第 4 點的等法等完（可與其他背景工作平行），每輪原始報告與 stderr 存在新的 `$A`；讀完將報告複製到 `_receipts/<工單名>.<attempt 名>.review.md`，核實結論追加在該份副本，原始報告保留：

```bash
# 工單狀態目錄同 docs/manual-dispatch.md 第 1 節（帶 workdir 雜湊）
D=~/.local/state/osslab-manager/<工單名>-$(printf '%s' "<workdir>" | sha256sum | cut -c1-8)
mkdir -p "$D" || exit $?
A=$(mktemp -d "$D/attempt-XXXXXXXX") || exit $?
printf 'attempt=%s\n' "$A"
E=$A/review.err
rc=0; bash ~/.agents/skills/osslab-manager/scripts/grok-readonly-review.sh <workdir> <prompt-file> \
  > "$A/review.md" 2> "$E" || rc=$?
printf '\nhelper exit=%s\n' "$rc" >> "$E"; exit "$rc"
```

提示要求：報告第一行就是「審查：grok / grok-4.7 medium @ <時間>」，前面不加開場白；Standards、Spec、Verification 三軸分開；每條附 嚴重度｜`file:line`｜問題｜程式證據｜建議修法；沒把握標「存疑」，沒問題直說不湊數；不得改檔。告訴審查員：它是唯讀，檢查你提供的執行證據即可，自己沒重跑不算驗證失敗；但證據缺漏、過期或不足仍擋驗收，由經理補。審查員仍常在標頭前加一句開場白；內容齊全就在核實段落記一筆，不必重跑。

## 六、逐條核實

審查員常看錯。每條都打開 `file:line` 對照原始碼與使用者授權：

- 成立：一輪審查的所有成立項合成**一張**修復單派給工人，不要一條一單。修復單只照審查員指定的 `file:line` 與修法做、沒動到其他行為的（機械修復），驗收重跑通過後可免第二輪 Grok，但仍須對最終 diff 執行 `code-review`；其他的再跑一輪 Grok（附上一輪報告、處置、變更 hunk、新證據與完整 diff）。
- 不成立：在報告末尾寫一行理由。
- 分清本次引入／暴露的缺陷與既有限制；既有限制記下，不默默擴大範圍。
- 移除 guard、放寬斷言要有決策來源；測試通過或審查員同意都不能決定新業務規則，這類回到人。

核實結論追加在審查報告末尾。Grok 之後照常完成 `code-review`；修改了實作就重跑受影響的驗證與最終 diff 的 `code-review`；Grok 是否重跑依上面的機械修復條件判定。

**經理直修（審查 nit）**：非阻擋的成立 nit，同時符合下列全部條件，經理可以自己改，不派修復單。阻擋級一律走工人（第七節）。

- 審查員已指定 `file:line` 與修法，經理只是照抄，不做設計；
- 每條不超過約 10 行，只動本單已改過的檔，不新增檔；
- 不改行為，驗收命令不變；不碰斷言、guard、skip、驗收命令；
- 不在排除域：錢、權限、庫存、對帳、migration、對外契約、憑證設定——這些再小也走工人。

記帳：本單先照第七節提交，直修在派下一張單前完成，改完重跑本單驗收命令，另做一個 commit，body 寫「經理直修：T<N> 第 k 條」，工單的「經理直修」段列出改了哪些檔與行。歸屬交給 `git blame`，總量用 `git log --grep 經理直修` 盤點。
退場：直修後任一驗收命令失敗 → 撤回直修，本單剩下的成立項全走工人修復單，並在工單記一筆。

**經理直修（文案）**：repo 裡純措辭、只複述程式與既有契約已有行為的描述性文字——README、驗證報告、說明註解——經理可以直接改，單次合計約 20 行內，不新增檔，不必派單。回執、spec／契約、測試、斷言與驗收命令不在內：回執是工人的說法，經理改了就變成證據；spec 改了就是改預期，回第一節。超過 20 行或拿不準的，累積到第八節前合成一張低階單派工人。記帳：不掛在任何工單上、不必重跑工單驗收；另做一個 commit，body 寫「經理直修：文案」，落在第八節整批 `code-review` 範圍內。

## 七、逐張本機提交（不 push）

一張單要同時滿足下面幾項，經理才為它做一個本機 commit：第四節驗收通過、`verify-change` 跑過、高階單的 Grok 各條已核實處置、`code-review` 通過。

- **阻擋級成立項不得拆單繞過**：成立且會造成錯誤行為、違反契約或讓驗證不成立的，修復單驗收通過前本單不提交，修好後和本單同一個 commit（body 列兩個工單號）。只有非阻擋的成立項可拆成跟進單，記在工單裡，各自一個 commit。
- `git add` 只加本單的檔，不用 `-A` 或 `.`；工人還在改的檔不要提交。
- 標題照 repo 的 commit 規範（很多 repo 禁裸 `WIP` 標題、禁日期）；body 寫工單號與驗證摘要。
- 提交後下一張單以新的 HEAD 為 base，審查與驗收都以 `git diff HEAD` 為範圍，不和前一張混在一起。
- 已 push 的提交不改寫；是否在 PR 前整理（squash）照 repo 規則。

## 八、收尾

push 前對整批（本輪起點 `..HEAD`）跑一次 `code-review`，看各張單之間的互相影響（例如後一張改了前一張依賴的東西）；token 不是問題時再加一輪 Grok，審查包換成整批 diff 與各單驗證證據。發現問題照第六、七節開修復單處理。

閘門都過、repo 規則允許時才 push 分支並開 PR，PR 說明帶工單號；merge 與部署照 repo 流程並經人同意。清暫存前，把審查結論、各條處置、驗證命令與結果、剩餘限制保存在工單或 PR；秘密要遮，大型原始 log 留 Git 外（`~/.local/state/osslab-manager/`），唯一驗收證據不留在 `/tmp`。盤點建的臨時環境此時清掉；`pi-sessions/` 裡用不到的 session 目錄一併刪：`base-head` 與該 worktree 目前 HEAD 不同的全刪（helper 只接續 HEAD 未變的 session）；同一 worktree 只留仍可能被接續的那個（手動派工是原單號，Relay 是該 task 最新成功 pi 工人的 attempt id）。

工單挪到 `_tickets/done/`。用白話告訴使用者：什麼能用了、會注意到什麼變化、還有哪些沒驗；分清「已 merge」與「已實際套用到 runtime」。

## 九、按職責分段換 session

一則 session 同時扛對齊、派工、驗收、提交，context 越滾越大，後段判斷會變差。工作分三段，段與段之間換 session；新段只讀交接檔（與 Relay 帳本）開工，不背前段對話。

| 段 | 職責（對應節） | 結束時已在檔案裡的產出 |
|---|---|---|
| 規格段 | 對齊、盤點、拆單、貼確認清單（第〇～二節） | 確認清單、工單檔、缺口表 |
| 施工段 | 派單、等待、收回執（第三節） | 回執、工作樹 diff |
| 驗收段 | 重跑驗收、審查、核實、派修復／跟進單、提交、收尾（第四～八節） | commit、驗證與審查證據 |

- 規格段 → 施工段一定換。
- 施工段一段可跑多張：不同 worktree 的獨立工單鏈可平行派；同一 worktree 仍一次一張、下一張以新 HEAD 為 base，所以同鏈是「施工 → 驗收 → 施工…」交替。
- 施工段 → 驗收段：高階單一定換；低階單可在同一 session 接著驗收，但第四節照實際 diff 升為高階的，照高階單換段。
- 修復迴圈留在驗收段：第四節第 4 點的跟進單、第六節的修復單由驗收段寫好就地派出、等回執、接著驗收，不回施工段——修復需要的正是這張單的驗收結論；阻擋級修復單照第七節與母單同一個 commit。修復／跟進單的 `blocked-by` 寫母單號，母單回執已讀、驗收結論已定就算解除，不套第二節「前置單已提交」的規則。
- 驗收段提交後，同鏈的下一張**新單**回施工段，由施工段依交接檔指向的回執存疑項把它寫細再派。
- 段內安全閥：同一段還沒結束，但已跑約 3 小時，或 runtime 回報 context 超過約 60%（沒有回報就不估），也在工單邊界換。
- 換段前提：工人結束、回執讀完、產出已在上表的檔案裡。卡在等人決定（第二節那三種）或使用者叫停，也停在段界寫交接。
- 走 Relay 時可把段當 owner（`<專案>-spec`／`-build`／`-accept`），段界用 `osrelay handoff`；後繼要重新 verify／review，本來就是驗收段的工作。

換段的交接檔內容（約 2KB 上限）、Paseo 自開下一則、接手 session 的信任規則：動作前先讀 `docs/handoff.md`。交接檔放 `~/.local/state/osslab-manager/handoffs/<短名>.md`，不進 git。第五節的 Grok 唯讀審查照舊；換 session、對齊公開 repo，都不改審查員。

## 規矩

- 工人不挪工單、不 commit、不審自己的活；審查員不改檔。
- 施工只准本 skill 的 helper CLI，不另寫 `workers.md`。宿主的 subagent 不能拿來寫實作：Claude 的 Agent／Task、Codex subagent 都算，Cursor 也不准 Cursor Task 或 `cursor-agent`。這是隔離邊界不是偏好——它們跑在經理的進程裡，沒有乾淨環境、pid 契約與回執協議，等於繞過整個工人隔離設計。
- 經理只提交自己驗收通過的單；push、PR 照 repo 流程，merge 與部署要人同意。經理自己寫進 repo 的只有驗收工具（第二節）與直修（第六節），產品碼一律走工人。
- 使用者中途插話先判斷是新決定還是隨口一說，只有新決定才改計畫。新決定擴大或改變範圍時，那部分回規格段：重貼確認清單（含「不做什麼」），新範圍的工單在段界交給下一段，不併進正在施工或驗收的這一段；進行中的 attempt 照舊等完收回，不中止、不重派。
- 裝軟體、換工人或模型、把程式碼交給新廠商，都先問人。
