# 等工人：各 host 的等法細節（osslab-manager 第三節第 4 點）

> 原則與 Claude Code／ZCode／Cursor 的等法在 SKILL.md 第三節第 4 點；本檔只放 Codex 受管 session 的具體做法。

Codex 單次 `exec_command`／`write_stdin` 最多約 30 秒就交還（要求 300 秒也一樣）。code-mode 由 `code_mode_host` 提供（`codex features list` 的 `code_mode` 顯示 false 也能用）；`@exec` 那行的 `yield_time_ms` 決定這個 cell 能在一次呼叫裡跑多久，省掉就會每幾秒交還一次。用 code-mode 在同一支 JS 裡迴圈到結束，一輪模型等完：

```js
// @exec: {"yield_time_ms": 3600000, "max_output_tokens": 800}
let r = await tools.write_stdin({session_id: <派工的 session_id>, chars: "", yield_time_ms: 30000});
while (r.exit_code === undefined || r.exit_code === null) {
  r = await tools.write_stdin({session_id: r.session_id ?? <派工的 session_id>, chars: "", yield_time_ms: 30000});
}
text(`exit_code=${r.exit_code}`);
```

沒有 code-mode 時，每次 `write_stdin` 都用 `yield_time_ms: 30000`。
