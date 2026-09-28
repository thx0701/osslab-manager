# 工人中斷後的備份與還原

先確認工人與其子程序都已停止，工作樹沒有其他寫入者，再執行：

```bash
bash <skill-dir>/scripts/backup-worktree.sh <workdir> <attempt-dir>/recovery
```

目的目錄必須不存在且位於 repo 外。成功才會產生 `SHA256SUMS` 並回傳 0；失敗留下的目錄不能當完整備份，下次另用新目錄。helper 不修改、清理或還原原工作樹。

備份包含 `base-head`、可還原 binary 的 `tracked.patch`、NUL 分隔的 `untracked.list` 與保留新增檔／symlink 的 `untracked.tar`。它保存相對 HEAD 的最終工作內容，不保存 index 的 staged／unstaged 區別；ignored 資料與 Git 不列出的特殊檔（例如 FIFO）不在範圍內，需另行盤點。含 submodule、未追蹤巢狀 repo 或清單中出現不支援的檔案型別時停止，先另外處理它們，不可把不完整 bundle 當成可以清理的依據。

還原先在獨立的乾淨 checkout 驗證，HEAD 必須等於 `base-head`。只使用本機產生且已核對的備份：

```bash
set -euo pipefail
cd <backup-dir>
sha256sum -c SHA256SUMS
# 在獨立 checkout，先確認 HEAD 與 base-head 相同。
if [[ -s tracked.patch ]]; then
  git -C <restore-workdir> apply --check <backup-dir>/tracked.patch
  git -C <restore-workdir> apply <backup-dir>/tracked.patch
fi
tar -xf <backup-dir>/untracked.tar -C <restore-workdir>
```

確認新增檔、binary、刪除與修改都可還原後，再核對原工作樹清理範圍與授權。不要用整樹 reset／clean 清掉工單、回執、別人的改動或未備份的 ignored 資料。做過收屍（備份成功或失敗）後的重派都不要帶 `--resume`；選擇繼承半套改動時，在工單列清楚後從零派工。
