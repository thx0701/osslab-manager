# 唯讀外部審查（SKILL 第五節細節）

> 審查順位與分級的規則在 SKILL 第五節；這裡是換人條件、審查包、命令與證據保存。

審查員依序：Codex GPT-6 Astra medium（`codex-readonly-review.sh`）→ GLM-5.3 max（`zcode-readonly-review.sh`）→ Grok（`grok-readonly-review.sh`，已停訂，到期前可用）；使用者或已定工單指定哪個就用哪個。使用者只指定某個階段（例如「規格給 GLM 審」）時，其他階段照順位，不跟著改。前一順位不能用才換下一個：helper 非零退出、啟動／認證／額度錯誤，或報告空白、缺標頭。換之前把失敗那輪的報告與 stderr 留在原 `$A`，核實段寫實際審查員與換人原因。報告內容不合意不是換人的理由，findings 照第六節核實。helper 自己不 fallback，換人由經理決定。審查員和經理或工人同一家（例如 Codex 經理配 Codex 審查、GLM 工人配 GLM 審查）時，在核實段註明「同系審查」，不稱異族。GLM-5.3-Flash 工人不變。

**審查分級**：`review-tier` 寫在工單 header，派單時先預估。

- **高階（外部審查＋`code-review`）**：碰到錢、權限、庫存、對帳、migration、對外契約或憑證設定的單；或任何改變檢查通過條件的單（動到斷言、guard、skip、驗收命令的預期結果）——就算它屬於「測試對齊」也一樣，這些改動改的是「通過的意義」。
- **低階（只 `code-review`，跳過本節）**：純文件、命名、格式、不動斷言的測試對齊；以及驗收工具與驗收清單的改動，只要沒改任何檢查的通過條件（例如加一項檢查、修工具跑不起來）。
- 預估只是預估：第四節照實際 diff 重定，碰到上列任一項就升高階；只升不降，拿不準算高階。
- 第八節 push 前的整批 `code-review` 不分級，一律照走。

準備審查包：工單與決策來源（含施工中問答：題目與經理回答，屬工單補充）、回執、完整 diff（只讀凍結成檔：`git diff HEAD`；新增檔已在第四節登錄）、repo 根與固定點 SHA、驗證證據（精確命令、工作目錄、exit code、原始輸出，對應受審版本；豁免要寫理由與未驗範圍）。「測試都過了」這種摘要不算證據。

把審查提示寫進檔案後，一律背景執行，照第三節第 4 點的等法等完（可與其他背景工作平行），每輪原始報告與 stderr 存在新的 `$A`；讀完將報告複製到 `_receipts/<工單名>.<attempt 名>.review.md`，核實結論追加在該份副本，原始報告保留：

```bash
# 工單狀態目錄同 docs/manual-dispatch.md 第 1 節（帶 workdir 雜湊）
D=~/.local/state/osslab-manager/<工單名>-$(printf '%s' "<workdir>" | sha256sum | cut -c1-8)
mkdir -p "$D" || exit $?
A=$(mktemp -d "$D/attempt-XXXXXXXX") || exit $?
printf 'attempt=%s\n' "$A"
E=$A/review.err
rc=0; bash ~/.agents/skills/osslab-manager/scripts/codex-readonly-review.sh <workdir> <prompt-file> \
  > "$A/review.md" 2> "$E" || rc=$?
printf '\nhelper exit=%s\n' "$rc" >> "$E"; exit "$rc"
```

換成 GLM 或 Grok 時，上面的 helper 換成 `zcode-readonly-review.sh` 或 `grok-readonly-review.sh`，等待與證據保存相同。Codex 與 GLM 的 helper 自己在報告第一行加標頭（「審查：codex / gpt-6-astra medium @ <時間>」「審查：zcode / GLM-5.3 max @ <時間>」），提示不必再要求。用 Grok 時提示要求報告第一行就是「審查：grok / grok-4.7 medium @ <時間>」，前面不加開場白；Standards、Spec、Verification 三軸分開；每條附 嚴重度｜`file:line`｜問題｜程式證據｜建議修法；沒把握標「存疑」，沒問題直說不湊數；不得改檔。告訴審查員：它是唯讀，檢查你提供的執行證據即可，自己沒重跑不算驗證失敗；但證據缺漏、過期或不足仍擋驗收，由經理補。審查員仍常在標頭前加一句開場白；內容齊全就在核實段落記一筆，不必重跑。
