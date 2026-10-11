# 工人實測：DeepSeek v4.1 Flash（RunInfra）對 Claude Haiku 5.5（2026-10-11）

**中文** | [English](2026-10-11-deepseek-vs-haiku.en.md)

## 結論

- **預設工人維持 DeepSeek v4.1 Flash（RunInfra）**：三張真實工單、三輪，9 次全部成功；速度是 Haiku 的 1.5～1.7 倍，按官方 API 價格換算多數情況也比較便宜。
- **Claude Haiku 5.5 只在指定時派**：走 Claude Pro 訂閱時每張單只用掉 5 小時額度約 1～2%，比讓 Opus 5.5 自己寫省很多；但比 DeepSeek 慢、耗時波動大，而且跟 Claude 經理共用同一個訂閱額度。
- 測試中找到的 Haiku helper 啟動誤判已修正上線（見「發現的問題」）。

## DeepSeek 的來源：RunInfra，不是 OpenRouter，也不是 DeepSeek 官方 API

本報告的 DeepSeek 數字**全部來自 RunInfra**（[runinfra.ai](https://runinfra.ai)）的 `deepseek-v4-1-flash` 端點。換供應商，速度與費用結論不一定成立。

- **它是什麼**：官網描述為「針對 agent 工作負載優化的模型託管 API」，主打 session-aware routing——同一個 agent session 的重複呼叫，會送到手上已有快取的副本，官方宣稱快取命中率 92～99% 以上、DeepSeek V4.1 Flash 輸出約 378 token／秒（2026-10-11 官網）。
- **我們為什麼選它**：2026-10-04 單輪對照，同一顆 `deepseek-v4-1-flash`，RunInfra 的工具第一跳與 OpenRouter 相近或略快，**長輸出約快 4～5 倍**，因此改為預設工人；OpenRouter 保留為退路（`scripts/pi-openrouter-worker.sh`）。
- **實測看得到快取效果**：t5a 第 1 輪 DeepSeek 的輸入共約 385 萬 token，其中約 96% 是快取讀取。
- **價格**：費用以 RunInfra 牌價計算——輸入 $0.14、快取讀取 $0.03、輸出 $0.58（每百萬 token，`scripts/runinfra-agent/models.json`）。官網 2026-10-11 標示 75 折，實際帳單會更低。

## 測試方法

- **工單**：relay 歷史中三張當時 DeepSeek 一次做完的真實工單——t5a（Python，修測試 fixture 的日期缺陷）、t4d（Python，設定與秘密處理）、t1（Go，電話路由保護與 SMS 查詢）。
- **公平性**：兩個工人各自從同一個起點 commit 開 worktree、拿同一份工單（只把原 worktree 路徑換成測試路徑）、同時並行施工；兩邊都是手動派工，都沒有施工中問經理的通道。跑三輪。
- **工人設定**：DeepSeek＝pi（RPC 驅動程式，thinking high）；Haiku＝Claude Code 2.1.286 無頭，effort high，Claude Pro 訂閱。
- **驗收**：重跑當時 relay 記錄的驗收命令。

## 結果

### 可靠性

| 工人 | 成功 |
|---|---|
| DeepSeek（RunInfra） | 9／9 |
| Haiku（修正前） | 4／7（3 次被 helper 誤判秒退） |
| Haiku（修正後） | 3／3，另以真 Claude CLI 直接呼叫 4／4 |

### 速度（只算成功的輪次）

| 工單 | DeepSeek 三輪 | Haiku 成功的輪次 | 中位數倍數 |
|---|---|---|---|
| t5a（Python） | 286／341／317 秒 | 488／420／1,475 秒 | Haiku 慢 1.5 倍 |
| t4d（Python） | 100／147／113 秒 | 183／205 秒 | Haiku 慢 1.7 倍 |
| t1（Go） | 244／286／367 秒 | 416／419 秒 | Haiku 慢 1.5 倍 |

DeepSeek 自己三輪之間也有 20～45% 的波動。Haiku t5a 第 3 輪的 1,475 秒是真實工作時間：它把測試丟到背景跑（7 個背景任務），背景完成後 Claude Code 再開新回合，一路做到結束。

### 費用（每張單，美元）

| 工單 | DeepSeek（RunInfra 牌價） | Haiku（換算官方 API 價） | 同樣 token 換成 Opus 5.5 價格 |
|---|---|---|---|
| t5a | 0.13～0.16 | 0.32～0.39 | 3.3～3.6 |
| t4d | 0.04～0.05 | 0.04～0.05 | 1.5～1.8 |
| t1 | 0.11～0.17 | 0.32～0.35 | 3.3 |

- Haiku 中大型單約貴 2.5 倍：輸出約是 DeepSeek 的兩倍，其中約 2/3 是思考 token；context 一長，單次 prompt 超過 10 萬 token 就換成較高單價（t5a 第 1 輪 47 次呼叫有 25 次）。
- Haiku 實際走 Pro 訂閱，不按 token 付費；上表是「如果改走 API」的換算。
- 「換成 Opus 5.5 價格」只是同樣 token 的粗略參考，Opus 自己寫時回合數與行為都會不同，不是實測值。

### 訂閱額度（Haiku）

每張單約用掉 Claude Pro 5 小時額度的 1～2%（例如第 3 輪 t5a 跑了 25 分鐘，從 5% 到 7%）。這個額度和 Claude.ai、同帳號其他 Claude Code session（包括 Claude 經理）共用。

### 品質

所有成功輪次的驗收命令都通過。**但這不足以比較品質**：t1 的驗收命令在起點版本就會通過；拿當時驗收過的最終測試當標準答案的檢查沒有跑完。本報告不判定哪一邊做得比較好。

## 發現的問題與修正

- **Haiku helper 啟動誤判（已修，osslab-manager PR #627）**：Claude Code 2.1.286 有時在 `system/init` 前先送 `system/ui_invalidate`，`scripts/claude-haiku-run.py` 原本只看第一行，於是把正常啟動判成 `model=missing` 秒退。現在 `init` 前最多暫存 20 個 system 事件，`init` 通過模型與認證檢查後依序寫出；`init` 前出現其他事件、非 JSON 或超過上限仍拒絕。失敗時的訂閱額度是 2～74%、狀態都是 allowed，與額度無關。
- **Claude CLI 回報的 Haiku 費用不可用**：CLI 2.1.286 不認得 `claude-haiku-5-5`（`unrecognized_model`、`costBasis: unknown`），`total_cost_usd` 是用 Opus 5.5 價格算的，比 Haiku 實際價格高約 10～35 倍。費用要用 token 數乘官方價格。
- **本次對照腳本的計時錯誤（已修正）**：前兩輪先等 DeepSeek 結束才收 Haiku，先結束的一方會被記成對方的耗時；只影響 3 次失敗的 Haiku 輪次（實際都在 2 秒內退出），成功輪次的耗時與 Claude 自己回報的 `duration_ms` 相差不到 2 秒。

## 限制

- 樣本小：三張工單、三輪；工單偏中小型（DeepSeek 2～6 分鐘）。
- 品質未比較（見上）。
- 沒有實測「Opus 5.5 自己寫」的成本與耗時。
- Haiku 的額度使用率會受同帳號其他 session 影響。
- DeepSeek 只測 RunInfra；OpenRouter 與 DeepSeek 官方 API 未在本次測試。

## 目前的安排

DeepSeek（RunInfra）是預設工人，RunInfra 暫停或額度問題時改走 OpenRouter 的同一顆模型，模型能力不夠再換 GLM 備援；Claude Haiku 只在使用者指定時手動派工，不進 Relay。
