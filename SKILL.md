---
name: osslab-manager
description: >-
  工單托管：經理（Claude Code／Codex）原則上不寫實作（直修與收尾模式例外），先盤點現況，再把開發拆成工單，
  預設派給 pi（本機執行、模型 DeepSeek v4.1 Flash 走 RunInfra）施工、ZCode（GLM-5.3-Flash，
  Coding Plan）為備援；使用者指定時可改派 Claude Code（claude-haiku-5-5，本機 Pro 訂閱，僅手動派工）。
  唯讀審查依序 Codex（gpt-6-astra，medium）→ ZCode GLM-5.3 max → Grok Build（grok-4.7，medium，已停訂），
  三者都可手動指定；經理負責驗收、
  逐條核實與逐張本機提交。
  觸發：走工單、托管、派出去、派給別的模型做、osslab-manager、manager skill、opus-manager（舊名）。
  平時照常自己動手，只在使用者要求時使用。
scope: company
tags: [all]
runtimes: [claude, codex]
notes: >-
  改編自 yanauto/opus-manager（MIT），舊名 opus-manager。公開副本是 https://github.com/thx0701/osslab-manager ；
  helper 用 $HOME 與 ZCODE_CLI_BIN，不寫死家目錄。經理只支援 Claude Code 與 Codex；ZCode 只當工人備援與 GLM 審查，Cursor 不做工單托管。
---

# 工單托管（OSSLab manager）

只在使用者要求托管時使用。經理是目前這則 session 的 bot，只支援 Claude Code 與 Codex（ZCode 只當工人備援與 GLM 審查，Cursor 不做工單托管），負責盤點、拆單、派單、驗收、核實與提交；人決定未定的業務規則。實作交給工人，經理不親自寫實作碼（驗收不過時也不偷偷修，開跟進單；例外只有第二節的經理驗收工具，與第六節的經理直修、收尾模式）。派工與審查都在背景跑，照第三節第 4 點的等法等完才收，不留未等待的調用、不用 nohup／`&` 脫離。施工只准本 skill 的 helper CLI（見「規矩」）。skill 走共用掛載 `~/.agents/skills/osslab-manager/`：Codex 直接掃 `~/.agents/skills`，Claude Code 的 view 是指向同一實體的 symlink。**Codex 經理在 Paseo 要用 Full Access（`auto-review` 模式網路受限，派工一定會被擋），推理固定 medium，goal 裡也不升 xhigh。**

細節在 docs，做那個動作前才讀：[workers](docs/workers.md)、[discovery](docs/discovery.md)、[tickets](docs/tickets.md)、[waiting](docs/waiting.md)、[manual-dispatch](docs/manual-dispatch.md)、[acceptance](docs/acceptance.md)、[review](docs/review.md)、[remediation](docs/remediation.md)、[closeout](docs/closeout.md)、[handoff](docs/handoff.md)、[relay](docs/relay.md)。

| 角色 | 執行者 | 呼叫 |
|---|---|---|
| 施工（預設） | pi＋`deepseek-v4-1-flash`（RunInfra），Relay 派工時可施工中發問 | `scripts/pi-runinfra-worker.sh [--resume <接續鍵>] <workdir> <ticket>` |
| 施工（只在指定時） | 同上，改走 OpenRouter | `scripts/pi-openrouter-worker.sh [--resume <接續鍵>] <workdir> <ticket>` |
| 施工（備援） | ZCode＋`GLM-5.3-Flash`（Coding Plan） | `scripts/zcode-cloud-worker.sh <workdir> <ticket>`（一律從零） |
| 施工（只在指定時） | Claude Code＋`claude-haiku-5-5`（本機 Pro 訂閱）；Relay 不路由 | `scripts/claude-haiku-worker.sh <workdir> <ticket>`（一律從零） |
| 審查（第一順位） | Codex 唯讀，`gpt-6-astra` medium | `scripts/codex-readonly-review.sh <workdir> <prompt-file>` |
| 審查（第二順位） | ZCode 完整 `GLM-5.3` max，只給 Read／Grep | `scripts/zcode-readonly-review.sh <workdir> <prompt-file>` |
| 審查（第三順位） | Grok Build `grok-4.7` medium，已停訂，到期前可用 | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |

工具：`scripts/wait-worker.sh`（等 pid 結束）、`scripts/backup-worktree.sh`（收屍備份）、`scripts/evidence-run.sh`（一條命令的輸出與指紋信封）、`scripts/acceptance-run.sh`（照清單跑多項檢查）；參數見 `docs/workers.md` 角色表。

路由已定，不另寫 `workers.md`；換模型或工具先問人，再改本 skill 開 PR。憑證只從既有 secret 檔載入，不進 argv／log／git。**選工人**：預設 DeepSeek（RunInfra）；RunInfra 暫停、503、啟動失敗、API 錯誤、額度或速率限制，同一張單 DeepSeek 驗收不過且像能力問題，或使用者指定時，改派 GLM-5.3-Flash（Relay 是 `--engine glm`），在 `claimed-by` 與工單「重派」寫實際引擎和原因。OpenRouter 與 Claude Haiku 只在使用者指定時用。**工人隔離**：工人以乾淨環境變數啟動，但仍看得到本機檔案，「不動 prod」只靠指示；工單不寫秘密，要碰 prod 的驗證由經理在第四節自己做，給工人拋棄式測試環境並寫明哪些共用資源不准刪。細節見 `docs/workers.md`。

開發順序照舊：`develop → implement → verify-change → code-review`；外部審查是 code-review 內的獨立意見。配套 skill 不在時改用工單驗收命令與第四～六節的重跑與核實，閘門不省。工人不 commit、不 push、不動 prod、不挪工單；可行時給工人獨立 git worktree，不派進別人正在用的髒 checkout。

## Relay 執行路徑（Codex／Claude Code 經理）

已安裝 `osrelay` 的主機（Paseo 上或一般終端機皆可），由 Relay 保管派工、等待、恢復與交接，本 skill 負責決策、驗收與提交；依要做的操作讀 [docs/relay.md](docs/relay.md) 的對應章節（開頭有索引）。Relay 的 SQLite 是執行狀態正本，下文的目錄搬移、手動 PID 等待、收屍與換段都改用 Relay CLI，不混用兩套派工；已有 Relay 任務而 runner 不可用時先恢復 runner，不另走 helper 重派。施工引擎只有 pi、glm，審查依序 codex、glm、grok。工作樹一變，舊 review 就不算數；accept 後仍要自己 commit，再 `finalize`。attempt 結束或工人發問時，Relay 經 Paseo 叫醒該 owner 最近一次 `bind` 的 session（Codex 預設開、Claude 預設關）；Relay 不開經理 session，自動開下一段只有 Paseo 的 `create_agent`（第九節）。未安裝 Relay 的 host 用下文手動流程。

## 〇、現況盤點（先量再問）

使用者問「完工了嗎」「做到哪了」「幫我補完」，或經理還不清楚現況時，先盤點再拆單；拿著交接檔接手的 session 看交接檔就算清楚現況，不因接手重盤。盤點是經理自己的活，不派工人：找完成度正本、跑所有既有測試層並對帳、在授權內唯讀查 prod、每個紅燈分成產品缺陷／測試過時／環境問題／規則未定，最後交出每列附命令與原樣輸出的缺口表，由使用者選範圍。先量再問。做法見 `docs/discovery.md`。

## 一、派單前：決策就緒

先讀專案規矩（`AGENTS.md`／`CLAUDE.md`）、相關程式與測試。每個新增或改變的驗收結果，在工單寫明決策來源：某版文件章節、已核准的 issue／PR，或使用者明確指示。

- **已定**：契約或使用者已決定 → 直接沿用，不重問。錢、庫存、權限也一樣；風險只決定驗證深度，營運核准規則照舊。
- **觀察**：程式、prod 現象或測試顯示的現況 → 標為現況證據；測試通過或 AI 寫的 spec 不等於人的意圖，不能拿來授權新業務行為。
- **未定**：新業務規則、影響結果的歧義、契約互相矛盾 → 先讀證據，只問剩下的決定。一輪問完前提已定的題目（要等別題答案的留到下一輪），每題附建議與具體例子，使用者要一題一題再改一次一題；要留在 repo 用 `grill-with-docs`，只討論用 `grill-me`，成契約用 `to-spec`。沉默不算同意。

派單條件：驗收可觀察、決策來源可追、失敗／邊界行為寫到、沒有未定的業務或架構選擇；會改變行為的單另要有一條驗收在起點會失敗（第二節「起點要失敗」）。

## 二、寫工單

照 `templates/ticket.md` 寫到 `_tickets/open/T<編號>-<短名>.md`；完整寫法見 `docs/tickets.md`。

- 一張單只做一件事，驗收寫命令、預期輸出與「為什麼這樣驗收」。
- **起點要失敗**：會改變行為的單，至少一條驗收命令在起點 commit 會失敗，而且失敗原因是這張單要改的行為；派單前經理在起點跑一次，寫進工單。要靠工人新寫的測試才分得出時寫「第四節補驗」；不改行為的單寫一句免除理由。
- **多項驗收一律用標準腳本**：一張單有 2 條以上必要檢查，就寫成一份清單（`tools/acceptance/<工單名>.txt`，每行 `id: 命令`）跟工單一起提交，工人、經理與 Relay `verify` 都只跑 `bash ~/.agents/skills/osslab-manager/scripts/acceptance-run.sh <repo 外的輸出目錄> tools/acceptance/<工單名>.txt`。repo 已有一條命令涵蓋全部檢查的 runner 時直接用它。經理不自寫聚合 runner、契約雜湊、刪項反例之類的後設基礎設施。
- **經理驗收工具**：量測、探針、UI 驅動派單前先提交進 repo（body 寫「經理驗收工具」），工人跑同一支；產品碼與既有斷言照舊走工人。**驗收工具從簡**：只寫本單現在要跑的檢查，不預先登記還沒派工的單；一條鏈最多開 1 張驗收工具單，之後補檢查或工具跑不起來由經理直接修（commit body 寫「經理直修：驗收工具」），不另開單、不跑外部審查（只做 `code-review`；已審過的 Relay task 仍照閘門重審）。驗收工具花的時間超過產品施工時，主動告訴使用者。
- 引用的工具必須是**已提交**版本；寫明只准動哪些檔、決策來源、回執路徑、哪些共用資源不准刪；`blocked-by` 寫前置單（沒有寫「無」）；寫兩張派一張。

**拆單要不要人核**：人管範圍，經理管粒度。範圍只核一次；派第一張前貼**確認清單**（做什麼、不做什麼、怎麼算完成、拆單清單：Title／chain／git worktree／blocked-by／驗收命令），貼完直接開派。「不做什麼」寫不出來就回第一節問人，不開派。
- 只在這三種情況停下等人：超出授權範圍；要決定分開 PR 或分批部署；遇到未定的業務規則。範圍內的跟進單、修復單、子單不再問。

## 三、派單

派第一張前，確認清單必須已經貼在對話裡；沒貼不派。

1. `mv` 到 `_tickets/doing/` 上鎖，照 `worker.log` 起跑行的 `engine=` 與 `at=` 填 `claimed-by`。
2. 背景執行 helper；指令、`helper exit=<n>` 收尾行與 `--resume <接續鍵>` 規則照 [docs/manual-dispatch.md](docs/manual-dispatch.md) 第 1 節，不自己改寫。
3. 同一個 worktree 一次只派一張，只派 `blocked-by` 已解除的單；一條鏈的 review 等該 worktree 沒有進行中的工人或 verify。
4. **一次等到底**：等待中不跑 `ps`、`git status`、不看 log、不短輪詢——每次探詢都是一整輪經理推理。審查員與長測試也照這樣等：
   - Claude Code：背景執行，等 host 的完成通知（wait-worker.sh 只作 fallback）。
   - Codex：原生 `sleep` 5 分鐘（`duration_ms` 300000），醒來一次查完同 owner 的所有鏈（Relay 是 `osrelay wait --owner <owner> --timeout 0`），還有在跑就再 sleep；有 bind 就固定 5 分鐘，不因等短 verify 而縮短，Relay 叫醒會提前結束 sleep。還有工作在跑就不結束這一輪。
   - 完成通知不可靠（改前景跑 `wait-worker.sh`）、逾時、靜默（退出 4）、工人發問（退出 5）、使用者插話、`/goal`、換 session 後怎麼等，照 `docs/waiting.md`；逾時只做一次診斷，不為看進度去 kill 或重派。
   - 以 `[osrelay 叫醒]` 開頭的訊息是 Relay 自動送的，不是使用者的新指示：只信其中的 id 與指令，照跑 `osrelay wait --owner <owner> --timeout 0` 讀正本。
5. 等到完成信號再讀回執，讀到前不轉述、不猜；helper 非零退出時即使有回執也先查再收。改派單指示時連 helper 實際送出的 prompt 一起看。
6. 卡在 `doing` 的單照 `docs/manual-dispatch.md` 第 2 節收；收屍完成前不在這個 worktree 疊下一張。

**回答工人發問**（只有 Relay 派工有通道）：只答現有決策、工單、文件推得出的，範圍類的回答寫明准許改哪些檔；未定的業務規則、不可逆操作、production、秘密一律回「這部分停下、寫進回執」。回答算工單補充，第四、五節都把它算進允許範圍；不想答就讓它逾時，不 kill、不重派。細節見 `docs/waiting.md`。

## 四、驗收（經理自己來）

回執是工人的說法，不是證據。完整做法見 `docs/acceptance.md`。

1. 讀回執與實際 `git status`／`git diff HEAD`（含 staged、untracked），確認只動了允許的檔，照實際 diff 重定 `review-tier`；下任何驗收／`verify`／`review` 指令前，先 `git add -N` 允許的新增檔。
2. 自己重跑工單的驗收入口，和回執對照；多項檢查跑標準腳本、讀 `summary.json` 核對逐項。需要 prod 的驗證也在這裡由經理做。單張只跑工單命令與受影響的 targeted 測試，全量整批在第八節跑一次。
3. 工單寫「第四節補驗」時，把工人新寫的測試放回起點跑：必須失敗，且原因是本單要改的行為；起點仍過就不算通過。
4. 讀存疑項並處理。不過：契約已定 → 寫跟進單 `T<編號>b` 再派；預期結果未定 → 回第一節。

長輸出的驗收用 `scripts/evidence-run.sh` 包起來，只有 wrapper exit=0、JSON 存在且 `verification_status=passed` 才算通過。最後一次實作變更後跑 `verify-change`；驗收過了先走第五、六節，提交在第七節。

## 五、唯讀外部審查（Codex → GLM → Grok）

審查員依序 Codex GPT-6 Astra medium → GLM-5.3 max → Grok（已停訂，到期前可用）；使用者或已定工單指定哪個就用哪個。前一順位不能用（helper 非零、啟動／認證／額度錯誤、報告空白或缺標頭）才換下一個並寫原因；報告不合意不是換人理由。同一家時註明「同系審查」。審查包、命令與證據保存見 `docs/review.md`。

**審查分級**：`review-tier` 寫在工單 header，派單時先預估。

- **高階（外部審查＋`code-review`）**：碰到錢、權限、庫存、對帳、migration、對外契約或憑證設定的單；或任何改變檢查通過條件的單（動到斷言、guard、skip、驗收命令的預期結果）——就算它屬於「測試對齊」也一樣，這些改動改的是「通過的意義」。
- **低階（只 `code-review`，跳過本節）**：純文件、命名、格式、不動斷言的測試對齊；以及驗收工具與驗收清單的改動，只要沒改任何檢查的通過條件（例如加一項檢查、修工具跑不起來）。
- 預估只是預估：第四節照實際 diff 重定，碰到上列任一項就升高階；只升不降，拿不準算高階。
- 第八節 push 前的整批 `code-review` 不分級，一律照走。

## 六、逐條核實

審查員常看錯。每條都打開 `file:line` 對照原始碼與使用者授權：成立的，一輪合成**一張**修復單派給工人；不成立的，在報告末尾寫一行理由；分清本次引入的缺陷與既有限制；移除 guard、放寬斷言要有決策來源，測試通過或審查員同意都不能決定新業務規則。核實結論追加在報告末尾，之後照常完成 `code-review`。完整條件、記帳與 Relay 做法見 `docs/remediation.md`，直修或收尾前先讀。

- **第 2 輪起只剩 minor，經理直接修**：同一張母單從第 2 輪起只剩已成立、非阻擋的 minor／nit，經理直接修，不再派 Flash；不能把阻擋項降級成 minor。改完重跑本單驗收並做最終 `code-review`，Relay 照目前指紋重驗重審，不沿用修改前的證據。
- **同一張單的 P1 修了 3 輪仍未收斂，必須升級**：以母單累計，換票、換 session 不歸零；第 4 輪不得再派 DeepSeek Flash 或 GLM Flash，改派已授權的更強施工者，或由經理收尾。
- **經理直修（審查 nit）**：其他非阻擋 nit 只在條件全符合時經理自己改：照抄審查員指定的修法、每條約 10 行內、只動本單已改過的檔、不改行為、不碰斷言或驗收命令、不在錢／權限／庫存／對帳／migration／對外契約／憑證設定。阻擋級一律走工人（第七節；收尾模式例外）。
- **經理直修（文案）**：README、說明註解這類只複述既有行為的措辭，單次約 20 行內、不新增檔，不必派單；回執、spec／契約、測試、斷言與驗收命令不在內。
- **收尾模式（經理自己做）**：Claude、Codex 經理都適用。剩下不超過 3 張小單、已上線且使用者在旁實測的調整期，或上面兩種收斂情況，經理一句話告訴使用者（例如「剩 N 項，改我自己做」）就自己改，使用者喊停就回到派工；收尾期間跟進單與修復單（含阻擋級）也由經理改。一般收尾碰到秘密、權限、錢、庫存、對帳、migration、對外契約或憑證設定的單不在內。閘門不省：起點要失敗、第四節驗收自己重跑、第五節審查、第七節逐張提交（body 寫「經理收尾：T<N>」）。

## 七、逐張本機提交（不 push）

第四節驗收通過、`verify-change` 跑過、高階單的外部審查已逐條處置、`code-review` 通過，經理才為這張單做一個本機 commit。

- **阻擋級成立項不得拆單繞過**：修復單驗收通過前本單不提交，修好後和本單同一個 commit（body 列兩個工單號）；只有非阻擋的成立項可拆成跟進單。
- `git add` 只加本單的檔，不用 `-A` 或 `.`；標題照 repo 的 commit 規範，body 寫工單號與驗證摘要。
- 下一張以新的 HEAD 為 base，審查與驗收都以 `git diff HEAD` 為範圍；已 push 的提交不改寫。

## 八、收尾

push 前對整批（本輪起點 `..HEAD`）跑一次 `code-review`，token 不是問題時再加一輪外部審查；閘門都過、repo 規則允許時才 push 開 PR，merge 與部署照 repo 流程並經人同意。審查結論、處置、驗證結果與剩餘限制存在工單或 PR，大型 log 留 Git 外；清掉盤點建的臨時環境與用不到的 `pi-sessions/`（細則見 `docs/closeout.md`）。工單挪到 `_tickets/done/`，用白話告訴使用者什麼能用了、會注意到什麼變化、還有哪些沒驗，分清「已 merge」與「已實際套用到 runtime」。

## 九、按職責分段換 session

工作分三段：規格段（第〇～二節：對齊、盤點、拆單、確認清單）、施工段（第三節：派單、等待、收回執）、驗收段（第四～八節：重跑驗收、審查、核實、修復、提交、收尾）。新段只讀交接檔（與 Relay 帳本）開工，不背前段對話。

- 規格段 → 施工段：有自動接力能力與持續授權就換，否則在本 session 續辦；不能自動接力不等於停工。施工段 → 驗收段：高階單有自動接力能力就換，低階單可在同一 session 接著驗收。
- 修復迴圈留在驗收段：跟進單、修復單在驗收段就地派出、等回執、接著驗收；它們的 `blocked-by` 寫母單號，母單回執已讀、驗收結論已定就算解除（不必等母單提交）。阻擋級修復單與母單同一個 commit。同鏈的下一張新單回施工段。
- 接手只讀必要的：確認時只讀交接檔；正式接任讀 SKILL 本文、下一張工單與該段要用的 docs；長 notes 只查需要的段落，同一份文件不重讀。細則見 `docs/handoff.md`「接手讀什麼」。
- 段內安全閥：已跑約 3 小時，或 context 到約 50% 就先寫好交接，到約 60% 不再開新一輪施工、驗證或審查，在最近的安全停點換段（沒有進行中的寫入、驗證或審查，結果已存檔），不必等整張單提交。新 session 開工就超過約 40% 時先縮小必讀範圍，不接連換空白 session。細則見 `docs/handoff.md`「context 安全閥」。
- 換段前提：工人結束、回執讀完、目前的結果、未決事項與 task 狀態已存檔（安全閥換段不必等整段產出或提交）；等人決定或使用者叫停也停在段界。後繼確認接任後，舊段停止施工，不兩邊同時派工；修復輪次照母單累計，不因換 session 歸零。走 Relay 時可把段當 owner，段界用 `osrelay handoff`，後繼要重新 verify／review。

交接檔（約 2KB，放 `~/.local/state/osslab-manager/handoffs/<短名>.md`，不進 git）、Paseo 自開下一則與接手信任規則：動作前先讀 `docs/handoff.md`。換 session 不改審查員。

## 規矩

- 工人不挪工單、不 commit、不審自己的活；審查員不改檔。
- 施工只准本 skill 的 helper CLI，不另寫 `workers.md`。宿主的 subagent 不能拿來寫實作：Claude 的 Agent／Task、Codex subagent 都算。這是隔離邊界不是偏好——它們跑在經理的進程裡，沒有乾淨環境、pid 契約與回執協議，等於繞過整個工人隔離設計。
- 經理只提交自己驗收通過的單；push、PR 照 repo 流程，merge 與部署要人同意。經理自己寫進 repo 的只有驗收工具（第二節），與第六節的直修、收尾模式；其餘產品碼一律走工人。
- 使用者中途插話先判斷是新決定還是隨口一說，只有新決定才改計畫。新決定擴大或改變範圍時，那部分回規格段：重貼確認清單（含「不做什麼」），新範圍的工單在段界交給下一段，不併進正在施工或驗收的這一段；進行中的 attempt 照舊等完收回，不中止、不重派。
- 裝軟體、換工人或模型、把程式碼交給新廠商，都先問人。
