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
  改編自 yanauto/opus-manager（MIT）。2026-09-27 由 opus-manager 改名為 osslab-manager；Codex 版 astra-manager 已於 2026-09-27 退役整併進本
  skill（歷史查 Git）；同輪經理擴及 ZCode：術語與路徑去 Claude 專屬假設，helper 對外契約不變。Cursor 個人目錄不得另放
  opus-manager 實體，改掛同一 `all/osslab-manager`。
---

# 工單托管（OSSLab manager）

只在使用者要求托管時使用。經理是目前這則 session 的 bot（Claude、ZCode、Codex 或 Cursor），負責盤點、拆單、派單、驗收、核實與提交；人決定未定的業務規則。實作交給工人，經理不親自寫實作碼（驗收不過時也不偷偷修，開跟進單；唯一例外是第六節的經理直修）。Claude／ZCode／Cursor 經理用 Bash 或 Shell 的背景執行派工與等審查；Codex 經理用受管 session（`exec_command`／`write_stdin`，工具名不同就用該 host 對應的受管背景機制），一樣不留未等待的調用、不用 nohup／`&` 脫離。施工只准本 skill 的 helper CLI（見「規矩」）。skill 檔與 scripts 走共用掛載 `~/.agents/skills/osslab-manager/`（各 runtime view 同源；Cursor 個人目錄同一實體）。**Codex 經理在 Paseo 要用 Full Access；`auto-review` 模式網路受限，派工一定會被擋。**

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 施工（預設） | pi CLI 在本機以 `-p` 無頭模式執行；模型 `deepseek/deepseek-v4.1-flash` 走 OpenRouter（按量計費，思考 `high`） | `scripts/pi-openrouter-worker.sh <workdir> <ticket>` |
| 施工（備援） | ZCode CLI 在本機以 yolo 模式執行；模型 `GLM-5.3-Flash` 走雲端（BigModel Coding Plan 訂閱，思考預設 Max） | `scripts/zcode-cloud-worker.sh <workdir> <ticket>` |
| 審查 | Grok Build，`grok-4.7`，reasoning effort `medium`，只給 Read／Grep | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |

路由已由本安裝定好，不重新摸工人、不另寫 `workers.md`。helper 不用 DGX Spark provider；憑證只從既有 secret 檔載入（`openrouter.env`、`glm-coding-plan.env`），不進 argv／log／git。要換模型或工具先問人，再改本 skill 開 PR。

**選工人**：預設 DeepSeek（2026-09-27 同票對照：小票約 7 倍快、中票略快，品質與誠實度相當）。遇到下列情況改派 GLM 備援，並在 `claimed-by` 寫實際引擎：DeepSeek 啟動失敗、API 錯誤、額度或速率限制；同一張單 DeepSeek 驗收不過且原因像是模型能力；使用者指定。
經理為 ZCode 時，備援工人與經理同屬 BigModel 系，且備援與本機 session 共用 Coding Plan 額度、可能互卡速率——預設仍 DeepSeek，異族審查照舊是 Grok；這種情況下改派備援等於換自己人施工，`claimed-by` 照實寫。
兩者的程式碼與工單內容都會送到各自的雲端模型供應商（OpenRouter／DeepSeek、BigModel），工單照舊不寫秘密。

**工人隔離的邊界**：helper 以乾淨環境變數啟動工人，不繼承經理 session 已匯出的 token 與業務憑證；但工人仍在本機跑 shell，看得到 Docker、網路與磁碟上的檔案（含 secret 檔），「不動 prod」只靠指示。所以工單不寫秘密或 secret 路徑；凡要碰 prod 的驗證（唯讀煙霧、XML-RPC、瀏覽器）由經理在第四節自己做；給工人拋棄式測試環境，並寫明哪些共用資源不准刪。

OSSLab 開發順序照舊：`develop → implement → verify-change → code-review`；Grok 審查是 code-review 內的獨立意見，不取代它。工人不 commit、不 push、不動 prod、不挪工單。可行時給工人獨立 git worktree；不把工人派進別人正在用的髒 checkout。

## 〇、現況盤點（先量再問）

使用者問「完工了嗎」「做到哪了」「幫我補完」，或經理還不清楚系統現況時，先盤點再拆單。盤點是經理自己的活，不派工人。

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
- 邊界寫明：只准動哪些檔、決策來源、回執路徑 `_receipts/<工單名>.receipt.md`、哪些共用資源不准刪。
- 寫兩張派一張；下一張常取決於上一張回執的存疑項。
- 每張在 `blocked-by` 寫前置工單，沒有寫「無」。前置單要在本 worktree 的 base 已有它的 commit 才算解除；它在別的 worktree 提交的，先 rebase 或 merge 進來再派。目錄就是狀態（`open`／`doing`／`done`），不另加狀態欄。
- 需求已走過 `to-tickets`：沿用它的切法與依賴，把票改寫進本 skill 模板——依賴寫進 `blocked-by`，`Verification` 當驗收起點，補到命令與預期輸出才派；`Status` 欄丟掉（目錄就是狀態），補上邊界、回執路徑等欄位。一組驗收命令說不清的票再拆，子單的 `blocked-by` 標回原單。

**拆單要不要人核**：人管範圍，經理管粒度。

- 範圍只核一次：盤點缺口表或使用者原始指示選定的範圍就是授權範圍，不重問。
- 粒度不等人核：派第一張前把拆單清單（Title／blocked-by／驗收命令）貼給使用者看，貼完直接開派。後面的單可以只有標題，寫細照舊寫兩張派一張；使用者插話照「規矩」判斷。
- 只在這三種情況停下等人：拆單超出授權範圍（順手改別的模組、多修一個 bug）；要決定分開 PR 或分批部署；遇到未定的業務規則（回第一節）。
- 範圍內的跟進單、修復單、切太大拆出的子單都不再問。

## 三、派單

1. `mv` 到 `_tickets/doing/`（挪成功＝上鎖），在 `claimed-by` 由經理填實際引擎：
   `pi / deepseek-v4.1-flash（OpenRouter）@ 時間`，改派備援時寫 `zcode / GLM-5.3-Flash（Coding Plan）@ 時間`。
2. 背景執行（各 runtime 的方式見開頭；一張單常跑一分鐘到數十分鐘）：

   ```bash
   mkdir -p ~/.local/state/osslab-manager/<工單名>
   # 預設 DeepSeek；改派備援時把 pi-openrouter-worker.sh 換成 zcode-cloud-worker.sh（參數相同）
   bash ~/.agents/skills/osslab-manager/scripts/pi-openrouter-worker.sh <workdir> <workdir>/_tickets/doing/<工單>.md \
     > ~/.local/state/osslab-manager/<工單名>/worker.log 2>&1
   ```

   要讓進行中的單不受 skill 中途更新影響，可凍結**整個 skill 目錄**再執行副本：`cp -rL ~/.agents/skills/osslab-manager ~/.local/state/osslab-manager/<工單名>/skill`，把 `git -C ~/.agents/skills/osslab-manager/ rev-parse HEAD` 記進工單；之後改跑 `…/<工單名>/skill/scripts/<helper>`。只複製腳本不行——helper 靠同一目錄的 `templates/receipt.md`，找不到會報錯退出。

3. 同一個 worktree 一次只派一張；不同 worktree 可以平行跑不同工單鏈。只派 `blocked-by` 已解除的單。
4. 看進度：`worker.log` 第一行是 helper 印的 `pid`，其餘輸出常到結束才出現。用 `ps -o etime= -p <pid>` 看是否還在跑、`git -C <workdir> status --porcelain` 看有沒有動檔；不要為了看進度去 kill 或重派。
5. 等完成通知再讀回執；讀到回執前不轉述、不猜結果。helper 非零退出時，即使有回執也要先查再收。
6. 改派單指示時，連 helper 實際送出的 prompt 一起看。擷取到的呼叫只證明送了什麼，不證明模型照做。
7. **卡在 `doing` 的單怎麼收**：
   - helper 非零退出＝失敗：照第 5 點查明原因後可重派。
   - `worker.log` 的 pid 已不在、也沒有回執＝工人死在半路。先確認真的死了：`ps -o etime=,args= -p <pid>` 要看 args 還是不是那支 helper／工人（PID 會被系統重用）。確認後收屍：停掉它留下的子程序（測試 server、shell）；`git -C <workdir> diff HEAD` 把半套改動存成 `~/.local/state/osslab-manager/<工單名>/partial-<次數>.patch`，再 revert，或在工單寫明繼承哪些；然後挪回 `_tickets/open/`。
   - 重派次數與原因記在**同一張工單**的 `重派` 欄，不開新檔。同一張單死兩次就改派備援或拆單。
   - 收屍完成前，不在這個 worktree 疊任何 `T<編號>b` 或下一張單。

工人若遇到未定的業務決策或契約衝突，應停下並在回執回報證據；經理回到第一節處理後再重派。

## 四、驗收（經理自己來）

回執是工人的說法，不是證據。

1. 讀回執與實際 `git status`／`git diff HEAD`（含 staged、untracked），確認只動了允許的檔、沒刪改不該動的；並照實際 diff 重定 `review-tier`（見第五節）。
2. 工人結束後，每條驗收命令自己重跑，和回執對照；有 UI／API 就實際打一次，需要 prod 的驗證也在這裡由經理做。
3. 讀存疑項並處理。
4. 不過：契約已定 → 寫跟進單 `T<編號>b` 再派；預期結果未定 → 回第一節。

最後一次實作變更後跑 `verify-change`。驗收過了還不提交，先走第五、六節審查，提交在第七節。

## 五、Grok 異族審查

**審查分級**：`review-tier` 寫在工單 header，派單時先預估。

- **高階（Grok＋`code-review`）**：碰到錢、權限、庫存、對帳、migration、對外契約或憑證設定的單；或任何動到斷言、guard、skip、驗收命令本身的單——就算它屬於「測試對齊」也一樣，這些改動改的是「通過的意義」。
- **低階（只 `code-review`，跳過本節）**：純文件、命名、格式、不動斷言的測試對齊。
- 預估只是預估：第四節照實際 diff 重定，碰到上列任一項就升高階；只升不降，拿不準算高階。
- 第八節 push 前的整批 `code-review` 不分級，一律照走。

準備審查包：工單與決策來源、回執、完整 diff（凍結成檔：`git diff HEAD`；新增檔先 `git add -N` 才會出現在 diff 裡）、repo 根與固定點 SHA、驗證證據（精確命令、工作目錄、exit code、原始輸出，對應受審版本；豁免要寫理由與未驗範圍）。「測試都過了」這種摘要不算證據。

把審查提示寫進檔案後，一律背景執行（各 runtime 的方式見開頭；可與其他背景工作平行；不要用 `nohup`、`&` 脫離，否則收不到完成通知），輸出存成 `_receipts/<工單名>.review.md`（第二輪 `.review-2.md`，不覆蓋）：

```bash
bash ~/.agents/skills/osslab-manager/scripts/grok-readonly-review.sh <workdir> <prompt-file> \
  > <workdir>/_receipts/<工單名>.review.md 2> ~/.local/state/osslab-manager/<工單名>/review.err
```

提示要求：報告第一行就是「審查：grok / grok-4.7 medium @ <時間>」，前面不加開場白；Standards、Spec、Verification 三軸分開；每條附 嚴重度｜`file:line`｜問題｜程式證據｜建議修法；沒把握標「存疑」，沒問題直說不湊數；不得改檔。告訴審查員：它是唯讀，檢查你提供的執行證據即可，自己沒重跑不算驗證失敗；但證據缺漏、過期或不足仍擋驗收，由經理補。審查員仍常在標頭前加一句開場白；內容齊全就在核實段落記一筆，不必重跑。

## 六、逐條核實

審查員常看錯。每條都打開 `file:line` 對照原始碼與使用者授權：

- 成立：一輪審查的所有成立項合成**一張**修復單派給工人，不要一條一單。修復單只照審查員指定的 `file:line` 與修法做、沒動到其他行為的（機械修復），驗收重跑通過即可，不必再審一輪；其他的再審一輪（附上一輪報告、處置、變更 hunk、新證據與完整 diff）。
- 不成立：在報告末尾寫一行理由。
- 分清本次引入／暴露的缺陷與既有限制；既有限制記下，不默默擴大範圍。
- 移除 guard、放寬斷言要有決策來源；測試通過或審查員同意都不能決定新業務規則，這類回到人。

核實結論追加在審查報告末尾。Grok 之後照常完成 `code-review`；修改了實作就重跑受影響的驗證與審查。

**經理直修（唯一例外）**：非阻擋的成立 nit，同時符合下列全部條件，經理可以自己改，不派修復單。阻擋級一律走工人（第七節）。

- 審查員已指定 `file:line` 與修法，經理只是照抄，不做設計；
- 每條不超過約 10 行，只動本單已改過的檔，不新增檔；
- 不改行為，驗收命令不變；不碰斷言、guard、skip、驗收命令；
- 不在排除域：錢、權限、庫存、對帳、migration、對外契約、憑證設定——這些再小也走工人。

記帳：本單先照第七節提交，直修在派下一張單前完成，改完重跑本單驗收命令，另做一個 commit，body 寫「經理直修：T<N> 第 k 條」，工單的「經理直修」段列出改了哪些檔與行。歸屬交給 `git blame`，總量用 `git log --grep 經理直修` 盤點。
退場：直修後任一驗收命令失敗 → 撤回直修，本單剩下的成立項全走工人修復單，並在工單記一筆。

## 七、逐張本機提交（不 push）

一張單要同時滿足下面幾項，經理才為它做一個本機 commit：第四節驗收通過、`verify-change` 跑過、高階單的 Grok 各條已核實處置、`code-review` 通過。

- **阻擋級成立項不得拆單繞過**：成立且會造成錯誤行為、違反契約或讓驗證不成立的，修復單驗收通過前本單不提交，修好後和本單同一個 commit（body 列兩個工單號）。只有非阻擋的成立項可拆成跟進單，記在工單裡，各自一個 commit。
- `git add` 只加本單的檔，不用 `-A` 或 `.`；工人還在改的檔不要提交。
- 標題照 repo 的 commit 規範（很多 repo 禁裸 `WIP` 標題、禁日期）；body 寫工單號與驗證摘要。
- 提交後下一張單以新的 HEAD 為 base，審查與驗收都以 `git diff HEAD` 為範圍，不和前一張混在一起。
- 已 push 的提交不改寫；是否在 PR 前整理（squash）照 repo 規則。

## 八、收尾

push 前對整批（本輪起點 `..HEAD`）跑一次 `code-review`，看各張單之間的互相影響（例如後一張改了前一張依賴的東西）；token 不是問題時再加一輪 Grok，審查包換成整批 diff 與各單驗證證據。發現問題照第六、七節開修復單處理。

閘門都過、repo 規則允許時才 push 分支並開 PR，PR 說明帶工單號；merge 與部署照 repo 流程並經人同意。清暫存前，把審查結論、各條處置、驗證命令與結果、剩餘限制保存在工單或 PR；秘密要遮，大型原始 log 留 Git 外（`~/.local/state/osslab-manager/`），唯一驗收證據不留在 `/tmp`。盤點建的臨時環境此時清掉。

工單挪到 `_tickets/done/`。用白話告訴使用者：什麼能用了、會注意到什麼變化、還有哪些沒驗；分清「已 merge」與「已實際套用到 runtime」。

## 規矩

- 工人不挪工單、不 commit、不審自己的活；審查員不改檔。
- 施工只准本 skill 的 helper CLI，不另寫 `workers.md`。宿主的 subagent 不能拿來寫實作：Claude 的 Agent／Task、Codex subagent 都算，Cursor 也不准 Cursor Task 或 `cursor-agent`。這是隔離邊界不是偏好——它們跑在經理的進程裡，沒有乾淨環境、pid 契約與回執協議，等於繞過整個工人隔離設計。
- 經理只提交自己驗收通過的單；push、PR 照 repo 流程，merge 與部署要人同意。
- 使用者中途插話先判斷是新決定還是隨口一說，只有新決定才改計畫。
- 裝軟體、換工人或模型、把程式碼交給新廠商，都先問人。
