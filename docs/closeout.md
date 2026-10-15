# 收尾（SKILL 第八節細節）

push 前對整批（本輪起點 `..HEAD`）跑一次 `code-review`，看各張單之間的互相影響（例如後一張改了前一張依賴的東西）；token 不是問題時再加一輪外部審查（照第五節順位），審查包換成整批 diff 與各單驗證證據。發現問題照第六、七節開修復單處理。

閘門都過、repo 規則允許時才 push 分支並開 PR，PR 說明帶工單號；merge 與部署照 repo 流程並經人同意。清暫存前，把審查結論、各條處置、驗證命令與結果、剩餘限制保存在工單或 PR；秘密要遮，大型原始 log 留 Git 外（`~/.local/state/osslab-manager/`），唯一驗收證據不留在 `/tmp`。盤點建的臨時環境此時清掉；`pi-sessions/` 裡用不到的 session 目錄一併刪：`base-head` 與該 worktree 目前 HEAD 不同的全刪（helper 只接續 HEAD 未變的 session）；同一 worktree 只留仍可能被接續的那個（手動派工是原單號，Relay 是該 task 最新成功 pi 工人的 attempt id）。

工單挪到 `_tickets/done/`。用白話告訴使用者：什麼能用了、會注意到什麼變化、還有哪些沒驗；分清「已 merge」與「已實際套用到 runtime」。

## 逐張本機提交原文（SKILL 第七節）

一張單要同時滿足下面幾項，經理才為它做一個本機 commit：第四節驗收通過、`verify-change` 跑過、高階單的外部審查各條已核實處置、`code-review` 通過。

- **阻擋級成立項不得拆單繞過**：成立且會造成錯誤行為、違反契約或讓驗證不成立的，修復單驗收通過前本單不提交，修好後和本單同一個 commit（body 列兩個工單號）。只有非阻擋的成立項可拆成跟進單，記在工單裡，各自一個 commit。
- `git add` 只加本單的檔，不用 `-A` 或 `.`；工人還在改的檔不要提交。
- 標題照 repo 的 commit 規範（很多 repo 禁裸 `WIP` 標題、禁日期）；body 寫工單號與驗證摘要。
- 提交後下一張單以新的 HEAD 為 base，審查與驗收都以 `git diff HEAD` 為範圍，不和前一張混在一起。
- 已 push 的提交不改寫；是否在 PR 前整理（squash）照 repo 規則。
