# 等工人：各 host 的等法細節（osslab-manager 第三節第 4 點）

> 原則與 Claude Code 的等法在 SKILL.md 第三節第 4 點；本檔只放 Codex 的具體做法。

Codex 經理用原生 `sleep`（`clock.sleep`）等，間隔 5 分鐘（`duration_ms: 300000`），醒來一次查完同 owner 的所有鏈，還有在跑就再 sleep。每次醒來都是一輪經理推理，外加重送整個 context：2026-10-13 兩個 Codex 經理用 1 秒 yield 的 code-mode cell 加 40～60 秒 sleep 輪詢，等待佔 token 四到五成。

原生 `sleep` 遇到這一輪的新輸入會提前結束（"Sleep interrupted by new input."）：使用者插話與 Relay 叫醒（Paseo steer）都會叫醒它。shell 與 code-mode 的工具呼叫不會被 steer 提前結束，訊息要等這次呼叫交還才看得到；`exec_command`／`write_stdin` 單次最多約 30 秒就交還（要求 300 秒也一樣），所以等待不要開長時間的 code-mode cell。

- **Relay**：醒來跑 `osrelay wait --owner <owner> --timeout 0`，退出碼見 `docs/relay.md` 第 4 點。
- **手動派工（沒有 Relay）**：醒來用一個 code-mode cell 查完所有派工 session，`exit_code` 還沒有就再 sleep：

```js
// @exec: {"yield_time_ms": 15000, "max_output_tokens": 400}
const ids = [<派工的 session_id>, ...];
const rs = await Promise.all(ids.map(id => tools.write_stdin({session_id: id, chars: "", yield_time_ms: 1000})));
text(rs.map((r, i) => `${ids[i]} exit_code=${r.exit_code ?? "running"}`).join("\n"));
```

換 session 後手上沒有原本的 session_id 時，改用 `wait-worker.sh <worker.log|review.err> 1`（124＝還在跑）。
