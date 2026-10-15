# 分段接力細節（osslab-manager 第九節）

> 職責分為規格／施工／驗收；能自動接力就換 session，不能時在本 session 續辦。Paseo 的成功標準是正常可開啟的新 session。

1. 交接寫到 `~/.local/state/osslab-manager/handoffs/<短名>.md`，不進 git，上限約 2KB。只放：使用者目標原話、確認清單的「不做什麼」、下一段是哪一段、workdir、本輪起點（整批 review 用）、HEAD、下一件的第一個動作、仍有效的決定與未定決定、阻擋項、累計修復輪次、目前 task／attempt 狀態、證據路徑與上一張回執。接手要讀的 SKILL 章節直接列出；長的 notes 與歷史證據只列成「查證索引」（附章節與用途），不當必讀。Relay 寫 goal／task id、owner、鏈名；有 goal 時用 `osrelay context <goal>`，不重抄回執。只有真的換 session 才必須寫交接，段內續辦不為換段而停。
2. 使用者已授權持續目標（goal、做到完、自動接力；Codex `/goal` 也算），且 Paseo 有建立與獨立 session 的能力：在安全段界自動開一則後繼，沿用同一 workspace、provider／模型／mode。Codex 固定 Full Access、medium。不確定設定就 `list_providers`／`list_models`，不猜。不改 provider，也不自動建立第二個後繼。
3. **先確認，後接任**：用 `create_agent` 的 `initialPrompt` 只要求讀交接檔、核對 HEAD 與下一張工單是否存在，回覆 `HANDOFF_ACK`、下一段與第一個動作，然後等待，不先派工；同一則 prompt 寫明下面「接手讀什麼」的規則（不展開 notes、同一份文件不重讀）。agent-scoped `create_agent` 預設建立子 agent；在同一 daemon 用原生 `paseo agent detach <agent-id> --json [--host <daemon>]` 轉為獨立 session，不移 workspace、不停程序。CLI 不可用時，只有已驗證的獨立建立入口才可替代，不手刪 label 猜測。
4. 核對 `get_agent_status`：workspaceId 與原 session 相同、labels 無 `paseo.parent-agent-id`、模型／有效思考／mode 符合設定、沒有 error 或待權限。從 `get_agent_activity` 讀到 `HANDOFF_ACK` 才算接手確認。detach 後的完成通知不保證回舊 session，不以等待通知代替確認；確認逾時只診斷同一個 agent，不重建。
5. 首次採用或 host 升版後，用實際 Paseo 瀏覽器驗收：新 session 出現在同一 workspace 的一般 session／頁籤列表，能點開交接內容，刷新後仍存在。使用 Paseo browserTools；沒有 browser host 時依 Chrome 規範 acquire 自己的 CDP lease，驗完 release。已有同版本的 fresh 證據可引用。只拿到 id 或 CLI 列表不算 UI 驗收成功。
6. 獨立 session、設定、交接確認與 UI 證據都通過，才移交責任：Relay 同 owner 只 `bind`（叫醒對象跟著移到新 session，舊段之後不要再 bind），換 owner 才 `handoff` 並把後繼 task id 送給新 session，由新 session bind。`accepted` 要先 finalize；已結案的 task 不 handoff，由下一張工單接續。後繼重新 verify／review。用 `send_agent_prompt` 指定下一件的第一個動作；Codex 若原來使用 `/goal`，在新 thread 明確設定同一 objective（goal 不跨 thread）。舊段把 session 名稱與 id 告訴使用者後停止施工，不等後繼完成，避免兩邊同時派工。
7. 開立／detach／設定／交接確認／UI 任一失敗：記錄已建立的 id 與原因，不派後繼做事、不移交 Relay owner。原 session 有足夠 context 就續辦。context 接近限制、使用者叫停或明確要求手動換時，才留交接與下列開頭；不要求每段由人重開。

   移交後送出下一步失敗或回覆不明時，先查同一 agent 是否已接收、是否在跑；已開始就由它續辦。確認未開始才由原 session 讀後繼 task 的 context、bind 新 owner 續辦，不重建 task 或盲目重送派工。

   ```text
   接手 osslab-manager <段名>段。先讀 <交接檔>。目標：<原話>。下一件：<第一個動作>。workdir：<路徑> HEAD：<sha>。
   ```

新 session 不因接手重做第〇節盤點；HEAD／工單不符時回報，實際驗收命令照舊重跑。只有使用者明確問現況，才重新盤點。

## 接手讀什麼（最小讀取）

換 session 是為了讓新段從乾淨的 context 開工，所以接手只讀用得到的：

1. **接手確認**：只讀交接檔，核對 workdir、HEAD 與下一張工單，就回 `HANDOFF_ACK`。這時不展開 notes、不重做盤點、不派工；上層規範要求的必讀文件照讀。
2. **正式接任**：讀 SKILL 本文、下一張工單，以及即將執行的動作要用的 docs：規格段看 `docs/discovery.md`、`docs/tickets.md`；施工段看 `docs/waiting.md`、`docs/manual-dispatch.md`；驗收段看 `docs/acceptance.md`、`docs/review.md`、`docs/remediation.md`、`docs/closeout.md`；驗收段要派修復或跟進單時，先補讀 `docs/tickets.md`、`docs/waiting.md` 與派工規則（`docs/manual-dispatch.md` 或 `docs/relay.md`）。走 Relay 時依操作讀 `docs/relay.md` 對應章節（開頭有索引）。
3. **查證**：先寫下要確認什麼，再搜尋 notes 的標題或關鍵字，只讀命中段落與必要上下文；不夠才擴讀。交接檔有連結不代表要整份讀。
4. **不重讀**：同一實體路徑（共用掛載的不同路徑算同一份）或同一內容、同版本、還在 context 裡的，就不再讀；版本變了只讀差異；壓縮後不在 context 了，才補讀目前動作要用的段落。
5. **按動作補讀**：其他 skill、helper 原始碼、專案規範在要用之前才讀；helper 照文件的參數與輸出用，失敗或要核實斷言時才讀實作。不能以省 context 為由略過規範要求的閱讀。

## context 安全閥

1. 開始第一個實際動作前看一次用量；已超過約 40%，先檢查是不是讀太多或重複讀，不要直接開一輪預期很長的工作。
2. 到約 50% 就先寫好交接；到約 60% 不再開新一輪施工、驗證或審查。已在跑的收完，在最近的安全停點換段：沒有進行中的寫入、驗證或審查，結果與未決事項已存檔，task 狀態明確；不必等整張單提交。
3. 新 session 開工就超過約 40%：先縮小必讀範圍或把下一步切小，不要接連換空白 session；必要基線本來就大時寫明原因。runtime 沒有用量回報就看時間（約 3 小時）與安全停點，不估百分比。

## 分段規則全文（SKILL 第九節）

一則 session 同時扛對齊、派工、驗收、提交，context 越滾越大，後段判斷會變差。工作分三段，有自動接力能力與授權才在段界換 session；新段只讀交接檔（與 Relay 帳本）開工，不背前段對話。

| 段 | 職責（對應節） | 結束時已在檔案裡的產出 |
|---|---|---|
| 規格段 | 對齊、盤點、拆單、貼確認清單（第〇～二節） | 確認清單、工單檔、缺口表 |
| 施工段 | 派單、等待、收回執（第三節） | 回執、工作樹 diff |
| 驗收段 | 重跑驗收、審查、核實、派修復／跟進單、提交、收尾（第四～八節） | commit、驗證與審查證據 |

- 規格段 → 施工段：有自動接力能力與持續授權就換，否則在本 session 續辦；不能自動接力不等於停工。
- 施工段一段可跑多張：不同 worktree 的獨立工單鏈可平行派；同一 worktree 仍一次一張、下一張以新 HEAD 為 base，所以同鏈是「施工 → 驗收 → 施工…」交替。
- 施工段 → 驗收段：高階單有自動接力能力就換，否則本 session 繼續；低階單可在同一 session 接著驗收。職責與驗收閘門仍分段，不要求每段都由人手動重開。
- 修復迴圈留在驗收段：第四節驗收不過時的跟進單（`acceptance.md` 第 5 點）、第六節的修復單由驗收段寫好就地派出、等回執、接著驗收，不回施工段——修復需要的正是這張單的驗收結論；阻擋級修復單照第七節與母單同一個 commit。Relay 的阻擋修復映射母 task 的新 attempt，見 `docs/relay.md`「阻擋修復票如何映射」。修復／跟進單的 `blocked-by` 寫母單號，母單回執已讀、驗收結論已定就算解除，不套第二節「前置單已提交」的規則。
- 驗收段提交後，同鏈的下一張**新單**回施工段，由施工段依交接檔指向的回執存疑項把它寫細再派。
- 接手只讀必要的：確認時只讀交接檔；正式接任讀 SKILL 本文、下一張工單與該段要用的 docs；長 notes 只查需要的段落，同一份文件不重讀。細則見 `docs/handoff.md`「接手讀什麼」。
- 段內安全閥：已跑約 3 小時，或 context 到約 50% 就先寫好交接，到約 60% 不再開新一輪施工、驗證或審查，在最近的安全停點換段（沒有進行中的寫入、驗證或審查，結果已存檔），不必等整張單提交。新 session 開工就超過約 40% 時先縮小必讀範圍，不接連換空白 session；沒有用量回報就看時間與安全停點。細則見 `docs/handoff.md`「context 安全閥」。
- 換段前提：工人結束、回執讀完、產出已在上表的檔案裡；依「context 安全閥」換段時，只要求目前的結果、未決事項與 task 狀態已存檔，不必等整段產出或提交。卡在等人決定（第二節那三種）或使用者叫停，也停在段界寫交接。
- 走 Relay 時可把段當 owner（`<專案>-spec`／`-build`／`-accept`），段界用 `osrelay handoff`；後繼要重新 verify／review，本來就是驗收段的工作。

換段的交接檔內容（約 2KB 上限）、Paseo 自開下一則、接手 session 的信任規則：動作前先讀 `docs/handoff.md`。交接檔放 `~/.local/state/osslab-manager/handoffs/<短名>.md`，不進 git。第五節的唯讀審查照舊；換 session、對齊公開 repo，都不改審查員。
