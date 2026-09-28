# 等工人：各 host 的等法細節（osslab-manager 第三節第 4 點）

> 原則在 SKILL.md：背景派出、一次等到底、不用 nohup／`&` 脫離。本檔放 Codex 受管 session 的具體做法；其他 host 一句話就能講完，留在 SKILL.md。

- Claude Code、ZCode：背景執行，等 host 的完成通知（ZCode 的背景 Bash 結束會主動回報；`wait-worker.sh` 只作 fallback）。
- Cursor 或任何沒有確認過完成通知的 host：前景跑 `scripts/wait-worker.sh`（用法見 SKILL.md 第三節第 4 點）。
- Codex：單次 `exec_command`／`write_stdin` 最多約 30 秒就交還（要求 300 秒也一樣）。用 code-mode 在同一支 JS 裡迴圈到結束，一輪模型等完：

  ```js
  // @exec: {"yield_time_ms": 3600000, "max_output_tokens": 800}
  let r = await tools.write_stdin({session_id: <派工的 session_id>, chars: "", yield_time_ms: 30000});
  while (r.exit_code === undefined || r.exit_code === null) {
    r = await tools.write_stdin({session_id: r.session_id ?? <派工的 session_id>, chars: "", yield_time_ms: 30000});
  }
  text(`exit_code=${r.exit_code}`);
  ```

  沒有 code-mode 時，每次 `write_stdin` 都用 `yield_time_ms: 30000`。
