# 驗收（SKILL 第四節細節）

回執是工人的說法，不是證據。

1. 讀回執與實際 `git status`／`git diff HEAD`（含 staged、untracked），確認只動了允許的檔（含施工中問答裡准許的檔，見 `osrelay status` 的 `questions`）、沒刪改不該動的；並照實際 diff 重定 `review-tier`（見第五節）。沒有進行中 attempt 時，先處理範圍外檔案（清理依 repo 規則與備份授權），再逐檔 `git add -N -- <允許的新增檔>`。這會改變指紋，必須在下任何驗收／`verify`／`review` 指令前完成；驗證後準備 diff 只讀、不再改 index。
2. 工人結束後，自己重跑工單的驗收入口，和回執對照；多項檢查的單依第二節只跑標準腳本這一條、每輪只用一條 `verify`，並讀它的 `summary.json` 核對逐項結果。有 API 就實際打一次，需要 prod 的驗證也在這裡由經理做。重跑範圍就是工單列出的命令：每張單的 `verify-change` 跑工單命令與受影響的 targeted 測試，不含全量；全量（多片、manifest、hash 對帳）整批只在第八節收尾跑一次，不為單張驗收重組全量或複製 runner。
3. 工單寫「第四節補驗」時，在起點開一棵拋棄式 worktree，只放進工人新增或修改的測試檔，跑同一條驗收命令（跑完移除）：必須失敗，且原因是本單要改的行為。起點仍過，代表驗收分辨不出改動，不算通過，照第 5 點處理。
4. 讀存疑項並處理。
5. 不過：契約已定 → 寫跟進單 `T<編號>b` 再派；預期結果未定 → 回第一節。

輸出很長的驗收命令用 `scripts/evidence-run.sh <out-dir> <label> -- <命令…>` 包起來：完整 log 與 JSON 信封（cwd、命令、命令 exit、wrapper exit、起訖時間、執行前後的 HEAD／diff／untracked 指紋）存到工單狀態目錄（[docs/manual-dispatch.md](manual-dispatch.md) 第 1 節的 `$D`），同名不覆蓋。只有 wrapper exit=0、JSON 存在且 `verification_status=passed` 才算通過；證據失敗或執行前後指紋不同不得驗收。版本變動先查原因，固定受驗版本後重跑；被 ignore 的檔、submodule 內部內容與外部環境不在指紋範圍。schema 2 保留原頂層版本欄位作為結束快照，完整版本在 `before`／`after`。通過時對話與審查包只引用 JSON 路徑和 exit code，失敗才讀它印的最後 20 行——通過的長 log 讀進對話，之後每一步都要重送。同一串命令寫到第三次、或驗收本身是多片全量時才用；短命令照舊直接跑。分片、manifest 這類跑法仍是各 repo 自己的 runner。

最後一次實作變更後跑 `verify-change`。驗收過了還不提交，先走第五、六節審查，提交在第七節。
