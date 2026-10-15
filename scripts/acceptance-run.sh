#!/usr/bin/env bash
# 多項驗收的標準入口（SKILL 第二節）：照清單依序跑每一項，失敗也續跑，逐項留 log 與 exit code，任一失敗整體非零。
# 用法：acceptance-run.sh <repo 外的輸出目錄> <清單檔>
#   清單每行「id: 命令」，命令以 bash -c 在目前目錄執行；空行與 # 開頭略過；id 限英數與 _.-，不得重複。
#   輸出到 <輸出目錄>/<清單名>-<台灣時間>/：每項 <id>.log（stdout＋stderr）與 summary.json；stdout 每項起訖各一行。
# 退出：0 全部通過；1 有項目失敗；2 用法、清單或輸出目錄不合格，或 summary.json 寫不出來（逐項紀錄留在 .records）。
# 執行前後的版本指紋不在這裡做：Relay verify 外層的 evidence-run.sh 已把關；不走 Relay 時自己用 evidence-run.sh 包。
set -uo pipefail

[[ $# -eq 2 && -f $2 ]] || { echo "usage: $0 <out-dir outside the repo> <manifest>" >&2; exit 2; }
manifest=$(readlink -f "$2")
out_root=$(readlink -m "$1")
repo=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -n $repo && ( $out_root == "$repo" || $out_root == "$repo"/* ) ]]; then
  echo "output dir must be outside the repo (logs would change the verified fingerprint): $out_root" >&2
  exit 2
fi

ids=() cmds=()
declare -A seen=()
while IFS= read -r line || [[ -n $line ]]; do
  [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
  if [[ ! $line =~ ^([A-Za-z0-9_.-]+):[[:space:]]*(.+)$ ]]; then
    echo "manifest line is not 'id: command': $line" >&2; exit 2
  fi
  id=${BASH_REMATCH[1]}
  [[ -z ${seen[$id]:-} ]] || { echo "duplicate id in manifest: $id" >&2; exit 2; }
  seen[$id]=1; ids+=("$id"); cmds+=("${BASH_REMATCH[2]}")
done < "$manifest"
(( ${#ids[@]} )) || { echo "manifest has no checks: $manifest" >&2; exit 2; }

name=$(basename "$manifest"); name=${name%.*}
dir=$out_root/$name-$(TZ=Asia/Taipei date +%Y%m%d-%H%M%S%z)
mkdir -p "$out_root" && mkdir "$dir" 2>/dev/null || dir=$(mktemp -d "$dir-XXXX") || exit 2
records=$dir/.records
failed=0
for i in "${!ids[@]}"; do
  id=${ids[$i]}; started=$(TZ=Asia/Taipei date -Iseconds); t0=$SECONDS
  echo "START $id"
  bash -c "${cmds[$i]}" > "$dir/$id.log" 2>&1 < /dev/null
  rc=$?
  if (( rc == 0 )); then word=PASS; else word=FAIL; failed=$((failed + 1)); fi
  echo "$word $id exit=$rc $((SECONDS - t0))s log=$dir/$id.log"
  printf '%s\t%s\t%s\t%s\n' "$id" "$rc" "$started" "$(TZ=Asia/Taipei date -Iseconds)" >> "$records"
done

python3 -I - "$manifest" "$dir" "$records" <<'PY'
import hashlib, json, re, subprocess, sys
manifest, out, records = sys.argv[1:]
commands = {}
for line in open(manifest, encoding="utf-8"):
    m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.+)$", line.rstrip("\n"))
    if m:
        commands[m[1]] = m[2]
checks = []
for row in open(records, encoding="utf-8"):
    cid, rc, started, finished = row.rstrip("\n").split("\t")
    checks.append({"id": cid, "command": commands[cid], "exit_code": int(rc), "log": f"{out}/{cid}.log",
                   "started": started, "finished": finished})
failed = [c["id"] for c in checks if c["exit_code"] != 0]
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None
summary = {"schema": 1, "manifest": manifest, "manifest_sha256": hashlib.sha256(open(manifest, "rb").read()).hexdigest(),
           "head": head, "checks": checks, "failed": failed, "status": "failed" if failed else "passed"}
with open(f"{out}/summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
PY
[[ $? -eq 0 && -s $dir/summary.json ]] || { echo "could not write $dir/summary.json; per-check records kept in $records" >&2; exit 2; }
rm -f "$records"
total=${#ids[@]}
if (( failed )); then echo "FAILED $failed/$total summary=$dir/summary.json"; exit 1; fi
echo "PASSED $total/$total summary=$dir/summary.json"
