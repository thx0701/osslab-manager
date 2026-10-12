# 工人實測：DeepSeek v4.1 Flash（RunInfra）對 Claude Haiku 5.5（2026-10-11）

**中文** | [English](2026-10-11-deepseek-vs-haiku.en.md)

## 結論

- **預設工人維持 DeepSeek v4.1 Flash（RunInfra）**：三張真實工單、三輪，9 次全部成功；速度是 Haiku 的 1.5～1.7 倍，按官方 API 價格換算多數情況也比較便宜。
- **Claude Haiku 5.5 只在指定時派**：走 Claude Pro 訂閱時每張單只用掉 5 小時額度約 1～2%，比讓 Opus 5.5 自己寫省很多；但比 DeepSeek 慢、耗時波動大，而且跟 Claude 經理共用同一個訂閱額度。

## DeepSeek 的來源

本報告的 DeepSeek 跑在 [RunInfra](https://runinfra.ai)：針對 agent 工作負載優化的託管服務，同一 session 的呼叫會命中快取（本次 DeepSeek 九輪的輸入有 92～97% 來自快取）。我們先前測過同一顆模型，RunInfra 的長輸出約比 OpenRouter 快 4～5 倍。換成 OpenRouter 或 DeepSeek 官方 API，速度與費用結論要重新量。費用以 RunInfra 牌價計算：輸入 $0.14、快取讀取 $0.03、輸出 $0.58（每百萬 token）。

## 測試方法

- **工單**：relay 歷史中三張當時 DeepSeek 一次做完的真實工單——t5a（Python，修測試 fixture 的日期缺陷）、t4d（Python，設定與秘密處理）、t1（Go，電話路由保護與 SMS 查詢）。
- **公平性**：兩個工人各自從同一個起點 commit 開 worktree、拿同一份工單（只把原 worktree 路徑換成測試路徑）、同時並行施工；兩邊都是手動派工，都沒有施工中問經理的通道。跑三輪。
- **工人設定**：DeepSeek＝pi（RPC 驅動程式，thinking high）；Haiku＝Claude Code 2.1.286 無頭，effort high，Claude Pro 訂閱。
- **驗收**：重跑當時 relay 記錄的驗收命令。

## 結果

### 可靠性

兩邊實際施工的輪次全部成功、驗收命令全過：DeepSeek 9 次，Haiku 7 次。

### 速度

| 工單 | DeepSeek 三輪 | Haiku 各輪 | 中位數倍數 |
|---|---|---|---|
| t5a（Python） | 286／341／317 秒 | 488／420／1,475 秒 | Haiku 慢 1.5 倍 |
| t4d（Python） | 100／147／113 秒 | 183／205 秒 | Haiku 慢 1.7 倍 |
| t1（Go） | 244／286／367 秒 | 416／419 秒 | Haiku 慢 1.5 倍 |

DeepSeek 自己三輪之間，最慢一輪比最快一輪多花 19～51% 的時間。Haiku t5a 第 3 輪的 1,475 秒是真實工作時間：它把測試丟到背景跑（7 個背景任務），背景完成後 Claude Code 再開新回合，一路做到結束。

### 費用（每張單，美元）

| 工單 | DeepSeek（RunInfra 牌價） | Haiku（換算官方 API 價） | 同樣 token 換成 Opus 5.5 價格 |
|---|---|---|---|
| t5a | 0.13～0.16 | 0.32～0.39 | 3.3～3.6 |
| t4d | 0.04～0.05 | 0.04～0.05 | 1.5～1.8 |
| t1 | 0.11～0.17 | 0.32～0.35 | 3.3 |

- Haiku 中大型單約貴 2.5 倍：輸出約是 DeepSeek 的兩倍，其中約 2/3 是思考 token；context 一長，單次 prompt 超過 10 萬 token 就換成較高單價（t5a 第 1 輪 47 次呼叫有 25 次）。
- Haiku 實際走 Pro 訂閱，不按 token 付費；上表是「如果改走 API」的換算，用 token 數乘官方價格。
- 「換成 Opus 5.5 價格」只是同樣 token 的粗略參考，Opus 自己寫時回合數與行為都會不同，不是實測值。這欄很可能高估：Anthropic 官方實測 Opus 5.5 在 SWE-bench Pro 每解一題約 $0.12（low）～0.29（high）（[來源](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)，API 牌價；題目與執行環境和本測試不同）。
- Claude Code 的快取寫入是 1 小時型，Haiku 與 Opus 兩欄都用 1 小時寫入價計算（每百萬 token：Haiku 5.5 $0.20，單次 prompt 超過 10 萬時用較高一級；Opus 5.5 $8）。

### 三種做法總計（三張單，待補測）

| 做法 | 三張單時間加總 | 三張單費用（美元） |
|---|---|---|
| A. Opus 經理＋DeepSeek 工人 | 工人 10.5～13.3 分鐘（三輪） | 工人 0.30～0.36（RunInfra 牌價） |
| B. Opus 經理＋Haiku 工人 | 工人 18.1～35.0 分鐘（第 1、3 輪） | 工人換算 API 價 0.75～0.77；實際走 Pro 訂閱 |
| C. Opus 5.5 自己寫 | 未測 | 未測 |

這張表還不完整：A、B 只算工人，經理（Opus）寫工單、等待、驗收的時間與 token 本次沒有量；C 沒有實測。**之後會補測**：同樣三張單，A、B 加上經理的時間與費用，C 由 Opus 5.5 無頭直接施工，三種做法並列總時間、總費用與訂閱額度。完整補測清單見 [README 路線圖](../../README.md#路線圖)。

### 訂閱額度（Haiku）

每張單約用掉 Claude Pro 5 小時額度的 1～2%（例如第 3 輪 t5a 跑了 25 分鐘，從 5% 到 7%）。這個額度和 Claude.ai、同帳號其他 Claude Code session（包括 Claude 經理）共用。

### 品質

所有輪次的驗收命令都通過。**但這不足以比較品質**：t1 的驗收命令在起點版本就會通過；拿當時驗收過的最終測試當標準答案的檢查沒有跑完。本報告不判定哪一邊做得比較好。osslab-manager 已因此新增規則：會改變行為的工單，至少一條驗收命令要在起點失敗。

## 限制

- 樣本小：三張工單、三輪；工單偏中小型（DeepSeek 2～6 分鐘），而且都是 DeepSeek 當時一次做完的單，對它有利。
- 品質未比較（見上）。
- 沒有實測「Opus 5.5 自己寫」的成本與耗時，也沒有算經理的花費；之後補測（見「三種做法總計」）。
- Haiku 的額度使用率會受同帳號其他 session 影響。
- DeepSeek 只測 RunInfra；OpenRouter 與 DeepSeek 官方 API 未在本次測試。

## 目前的安排

DeepSeek（RunInfra）是預設工人，RunInfra 不能用（暫停、額度等）或模型能力不夠，就換 GLM-5.3-Flash 備援；OpenRouter 的同一顆模型只在使用者指定時用；Claude Haiku 只在使用者指定時手動派工，不進 Relay。
