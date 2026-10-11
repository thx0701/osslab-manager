# GLM-5.3 High 唯讀審查

日常預設 Grok。使用者或工單指定 GLM 時，用完整 **GLM-5.3**、ZCode **High**；備援工人仍是 GLM-5.3-Flash。GLM 工人交 GLM 審查時註明同系審查。

```bash
bash ~/.agents/skills/osslab-manager/scripts/zcode-readonly-review.sh <workdir> <review-prompt-file>
# Relay（需支援 --engine 的版本）
osrelay review <task> --owner <owner> --key <新審查鍵> --engine glm --prompt <review-prompt-file>
```

兩個位置參數與 Grok helper 相同，完整報告印 stdout、pid／啟動資訊印 stderr。照 SKILL.md 的受管等待與證據保存方式執行；退出非零不可當有效審查，非空報告也不代表沒有 findings。

helper 從既有 `~/.openclaw/secrets/glm-coding-plan.env` 讀憑證，只把 key 放在乾淨的子程序環境；使用 Coding Plan 的 Anthropic 相容入口。`ZCODE_CLI_BIN` 可指定本機 CLI。不要把 key 放工單、prompt、argv 或 log；不修改使用者的 HOME 或全域設定。凍結副本須含整份 skill，尤其 `scripts/zcode-review.py`。

ZCode 0.16.3 的 help 宣稱支援 `--settings`、`--allowed-tools`，但實際 parser 會拒絕。這條路徑使用原生 `app-server --stdio`：`session/create` 明設 plan、Read/Grep allowlist、High，停用記憶與標題生成；`session/setThoughtLevel` 明設 High 且不保存成 workspace 預設。送出前及完成後讀 `session/read`，模型、High 或 plan 不符就失敗，不默默換模型或升到 Max。

只有成功 terminal event 與非空 assistant text 才輸出報告，排除 reasoning。工具權限／互動要求、取消、空報告、backend 消失或逾時都失敗。15 分鐘仍未完成會退出；原生 session DB 放 `~/.local/state/osslab-manager/zcode-reviews/` 的每輪私人目錄，不放受驗 repo；結束只關掉本輪 backend，不碰其他 ZCode session。Relay 另核對受驗工作樹未變。

runtime 僅供該輪除錯，不是正式驗收證據。報告、stderr 與驗證 JSON 存妥且結案後，依 host 暫存清理規則，只保留最近 3 輪及尚未結案的 runtime；執行中不清理。清理只限本 helper 建立的 `zcode-reviews/review-*`，不動全域 ZCode 設定或其他 session。
