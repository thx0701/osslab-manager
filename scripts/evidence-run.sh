#!/usr/bin/env bash
set -euo pipefail

# 驗收證據信封：在目前目錄跑一條命令，完整輸出存 <label>.log，
# 另寫 <label>.json（cwd、命令、exit、起訖時間、HEAD、diff HEAD 與 untracked 檔的雜湊、log 路徑）。
# stdout 只印一行摘要，失敗才多印 log 最後 20 行——通過的長輸出不進對話。
# 只管記錄；分片、manifest 這類跑法留在各 repo 自己的 runner。
usage() {
  printf 'usage: %s <out-dir> <label> -- <command> [args...]\n' "$0" >&2
  exit 2
}

[[ $# -ge 4 && $3 == -- && $2 =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$ ]] || usage
out_dir=$1
label=$2
shift 3

# 證據放 repo 外（或已被 ignore 的目錄）；放在工作樹裡會變成 untracked，連自己的 log 都算進雜湊。
top=$(git rev-parse --show-toplevel 2>/dev/null || true)
target=$(readlink -m "$out_dir")
if [[ -n $top && ( $target == "$top" || $target == "$top"/* ) ]] && ! git check-ignore -q "$target"; then
  printf 'out-dir %s is inside the work tree %s and not ignored; use the ticket state dir ~/.local/state/osslab-manager/<ticket>-<workdir-hash8>/ (SKILL.md 3.2)\n' \
    "$target" "$top" >&2
  exit 2
fi
mkdir -p "$out_dir" && chmod 700 "$out_dir"
out_dir=$(readlink -f "$out_dir")
log=$out_dir/$label.log
json=$out_dir/$label.json
# 證據不覆蓋；重跑換一個 label（例如 -2）。
if [[ -e $json || -e $log ]]; then
  printf 'evidence %s already exists in %s; use a new label\n' "$label" "$out_dir" >&2
  exit 2
fi

now() { TZ=Asia/Taipei date '+%Y-%m-%dT%H:%M:%S%:z'; }
started=$(now)
set +e
"$@" >"$log" 2>&1
rc=$?
set -e
ended=$(now)

# 寫 JSON 失敗也不能吞掉原命令的結束碼。
python3 - "$json" "$log" "$rc" "$started" "$ended" "$@" <<'PY' || printf 'evidence: failed to write %s\n' "$json" >&2
import hashlib, json, os, subprocess, sys

path, log, rc, started, ended, *argv = sys.argv[1:]

def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None

head = git("rev-parse", "HEAD")
diff = git("diff", "HEAD", "--binary")
def sha256_file(path):
    # 串流讀取：untracked 裡出現大檔（dump、build 產物）也不會把整檔吃進記憶體。
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

untracked = []
names = git("ls-files", "--others", "--exclude-standard", "-z")
for name in (names or b"").split(b"\0"):
    if not name:
        continue
    p = os.fsdecode(name)
    try:
        digest = sha256_file(p)
    except OSError:
        digest = None
    untracked.append({"path": p, "sha256": digest})

record = {
    "schema": 1,
    "cwd": os.getcwd(),
    "argv": argv,
    "exit_code": int(rc),
    "started": started,
    "ended": ended,
    "head": head.decode().strip() if head else None,
    "diff_head_sha256": hashlib.sha256(diff).hexdigest() if diff is not None else None,
    "untracked": untracked,
    "log": log,
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY

printf 'evidence label=%s exit=%s json=%s log=%s\n' "$label" "$rc" "$json" "$log"
if (( rc != 0 )); then
  tail -n 20 "$log"
fi
exit "$rc"
