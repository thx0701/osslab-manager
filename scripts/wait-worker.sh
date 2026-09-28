#!/usr/bin/env bash
set -euo pipefail

# 阻塞等工人／審查員的 pid 結束，只印一行。
#   exit 0   ：已結束，印 exited … code=<n>（n 是 helper 的結束碼，成敗看它）
#   exit 125 ：已結束，但 log 最後一行沒有 helper exit=<n>，印 code=unknown
#   exit 124 ：等滿 max_seconds 還在跑，印 running …
# 用途：等的不是本 session 起的進程（例如換 session 後），或 host 沒有完成通知時，
# 用一次等待取代「幾秒問一次 ps／git status」。
# 第一個參數給 worker.log／review.err（取第一個 pid=<n> 與 proc_start=<n>），或直接給 pid。
usage() {
  printf 'usage: %s <pid|worker-log> <max_seconds>\n' "$0" >&2
  exit 2
}

[[ $# -eq 2 && $2 =~ ^[1-9][0-9]*$ ]] || usage
max=$2
log=
expected=
if [[ $1 =~ ^[1-9][0-9]*$ ]]; then
  pid=$1
elif [[ -f $1 ]]; then
  log=$1
  pid=$(grep -oE -m1 '(^| )pid=[0-9]+' "$log" | cut -d= -f2 || true)
  [[ -n $pid ]] || { printf 'no pid=<n> line in %s\n' "$log" >&2; exit 2; }
  expected=$(grep -oE -m1 'proc_start=[0-9]+' "$log" | cut -d= -f2 || true)
else
  usage
fi

now() { TZ=Asia/Taipei date '+%F %T %z'; }
# /proc/<pid>/stat 的程序名可能含空白，從最後一個 ")" 之後數欄位；starttime 是第 22 欄。
started_at() {
  local stat fields
  read -r stat 2>/dev/null <"/proc/$pid/stat" || return 0
  read -ra fields <<<"${stat##*) }"
  printf '%s' "${fields[19]:-}"
}
# helper 起跑時記下的 proc_start 最準；只給 pid 時退而用等待開始當下的值。
# 對不上就是 pid 已被無關程序重用，當作原本的進程已結束。
[[ -n $expected ]] || expected=$(started_at)
alive() {
  kill -0 "$pid" 2>/dev/null || return 1
  [[ -z $expected || $(started_at) == "$expected" ]]
}

start=$SECONDS
while alive; do
  left=$((max - (SECONDS - start)))
  if (( left <= 0 )); then
    printf 'running pid=%s waited=%ss at=%s\n' "$pid" "$((SECONDS - start))" "$(now)"
    exit 124
  fi
  sleep $((left < 5 ? left : 5))
done

# 派工指令在 helper 結束後才補一整行 helper exit=<n>；只認 log 的最後一行，
# 工人自己的輸出裡出現同樣字串不算。給它幾秒寫進來。
if [[ -n $log ]]; then
  for _ in 1 2 3 4 5; do
    last=$(tail -n1 "$log")
    if [[ $last =~ ^helper\ exit=([0-9]+)$ ]]; then
      printf 'exited pid=%s code=%s waited=%ss at=%s\n' "$pid" "${BASH_REMATCH[1]}" "$((SECONDS - start))" "$(now)"
      exit 0
    fi
    sleep 1
  done
fi
printf 'exited pid=%s code=unknown waited=%ss at=%s\n' "$pid" "$((SECONDS - start))" "$(now)"
exit 125
