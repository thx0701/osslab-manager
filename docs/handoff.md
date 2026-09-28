# 分段換 session 細節（osslab-manager 第九節）

> SKILL.md 第九節只留分段規則與入口；本檔是換段動作的正本，動作前先讀完。

1. 交接寫到 `~/.local/state/osslab-manager/handoffs/<短名>.md`，不進 git，上限約 2KB。只放：使用者目標原話、確認清單的「不做什麼」、下一段是哪一段（規格／施工／驗收）、workdir、本輪起點（第八節整批 review 用；尚無提交就同 HEAD）、HEAD、下一件的第一個動作、還沒定的決定、證據路徑（含上一張回執；Relay 任務寫 task id；有最大項就寫 goal id，鏈只寫 chain 名與 worktree 路徑）。不貼對話、diff、盤點結果，證據留在路徑裡。有 goal id 時，下一手用 `osrelay context <goal id>` 讀各節狀態，不在交接檔重抄回執。
2. 使用者下過持續目標，而且這則經理跑在 Paseo：自己開下一則。持續目標是 Codex `/goal <objective>`，或使用者說的 goal、做到完、自動接力。用 Paseo `create_agent`，同一個 workspace；provider、模型、mode 沿用目前這則（Codex 的 effort 照 SKILL.md 開頭固定 medium，不沿用 high／xhigh），不確定就先 `list_providers` 與 `list_models`。`initialPrompt` 只要下一則先讀交接檔，再做下一件的第一個動作。新 session 若是 Codex，用同一個 objective 再下一次 `/goal`（goal 綁在原來的 thread）。Codex 派工仍要 Full Access。開完把新 agent id 告訴使用者。開不起來就改走第 3 點。
3. 沒有持續目標，或不在 Paseo：停下。把交接路徑和下面這段開頭交給使用者，請他開新 session。這則不再做下一個段落。

   ```text
   接手 osslab-manager <段名>段。先讀 <交接檔>。目標：<原話>。下一件：<第一個動作>。workdir：<路徑> HEAD：<sha>。
   ```

4. 使用者說留在這則，才繼續。一次只開一則下一手。
5. 新 session 信任交接檔：只核 HEAD 與下一張工單檔在不在，相符就做下一件的第一個動作；不符就停下回報。不因接手重做第〇節盤點；使用者在新 session 問第〇節那些問題（完工了嗎、做到哪了、幫我補完）才重走。驗收命令照舊重跑。
