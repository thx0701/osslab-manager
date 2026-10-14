# 分段接力細節（osslab-manager 第九節）

> 職責分為規格／施工／驗收；能自動接力就換 session，不能時在本 session 續辦。Paseo 的成功標準是正常可開啟的新 session。

1. 交接寫到 `~/.local/state/osslab-manager/handoffs/<短名>.md`，不進 git，上限約 2KB。只放：使用者目標原話、確認清單的「不做什麼」、下一段是哪一段、workdir、本輪起點（整批 review 用）、HEAD、下一件的第一個動作、未定決定、證據路徑與上一張回執。Relay 寫 goal／task id、owner、鏈名；有 goal 時用 `osrelay context <goal>`，不重抄回執。只有真的換 session 才必須寫交接，段內續辦不為換段而停。
2. 使用者已授權持續目標（goal、做到完、自動接力；Codex `/goal` 也算），且 Paseo 有建立與獨立 session 的能力：在安全段界自動開一則後繼，沿用同一 workspace、provider／模型／mode。Codex 固定 Full Access、medium。不確定設定就 `list_providers`／`list_models`，不猜。不改 provider，也不自動建立第二個後繼。
3. **先確認，後接任**：用 `create_agent` 的 `initialPrompt` 只要求讀交接檔、核對 HEAD 與下一張工單是否存在，回覆 `HANDOFF_ACK`、下一段與第一個動作，然後等待，不先派工。agent-scoped `create_agent` 預設建立子 agent；在同一 daemon 用原生 `paseo agent detach <agent-id> --json [--host <daemon>]` 轉為獨立 session，不移 workspace、不停程序。CLI 不可用時，只有已驗證的獨立建立入口才可替代，不手刪 label 猜測。
4. 核對 `get_agent_status`：workspaceId 與原 session 相同、labels 無 `paseo.parent-agent-id`、模型／有效思考／mode 符合設定、沒有 error 或待權限。從 `get_agent_activity` 讀到 `HANDOFF_ACK` 才算接手確認。detach 後的完成通知不保證回舊 session，不以等待通知代替確認；確認逾時只診斷同一個 agent，不重建。
5. 首次採用或 host 升版後，用實際 Paseo 瀏覽器驗收：新 session 出現在同一 workspace 的一般 session／頁籤列表，能點開交接內容，刷新後仍存在。使用 Paseo browserTools；沒有 browser host 時依 Chrome 規範 acquire 自己的 CDP lease，驗完 release。已有同版本的 fresh 證據可引用。只拿到 id 或 CLI 列表不算 UI 驗收成功。
6. 獨立 session、設定、交接確認與 UI 證據都通過，才移交責任：Relay 同 owner 只 `bind`（叫醒對象跟著移到新 session，舊段之後不要再 bind），換 owner 才 `handoff` 並把後繼 task id 送給新 session，由新 session bind。`accepted` 要先 finalize；已結案的 task 不 handoff，由下一張工單接續。後繼重新 verify／review。用 `send_agent_prompt` 指定下一件的第一個動作；Codex 若原來使用 `/goal`，在新 thread 明確設定同一 objective（goal 不跨 thread）。舊段把 session 名稱與 id 告訴使用者後停止施工，不等後繼完成，避免兩邊同時派工。
7. 開立／detach／設定／交接確認／UI 任一失敗：記錄已建立的 id 與原因，不派後繼做事、不移交 Relay owner。原 session 有足夠 context 就續辦。context 接近限制、使用者叫停或明確要求手動換時，才留交接與下列開頭；不要求每段由人重開。

   移交後送出下一步失敗或回覆不明時，先查同一 agent 是否已接收、是否在跑；已開始就由它續辦。確認未開始才由原 session 讀後繼 task 的 context、bind 新 owner 續辦，不重建 task 或盲目重送派工。

   ```text
   接手 osslab-manager <段名>段。先讀 <交接檔>。目標：<原話>。下一件：<第一個動作>。workdir：<路徑> HEAD：<sha>。
   ```

新 session 不因接手重做第〇節盤點；HEAD／工單不符時回報，實際驗收命令照舊重跑。只有使用者明確問現況，才重新盤點。
