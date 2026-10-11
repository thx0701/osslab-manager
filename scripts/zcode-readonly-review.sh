#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 2 && -d "$1" && -f "$2" ]] || {
  printf 'usage: %s <workdir> <review-prompt-file>\n' "$0" >&2
  exit 2
}
workdir=$(readlink -f "$1")
prompt_file=$(readlink -f "$2")
script_dir=$(dirname "$(readlink -f "$0")")
zcode_bin="${ZCODE_CLI_BIN:-$HOME/.local/share/zcode/squashfs-root/resources/glm/zcode.cjs}"
[[ -f "$zcode_bin" && -f "$script_dir/zcode-review.py" ]] || {
  printf 'ZCode CLI or frozen review protocol helper is unavailable\n' >&2
  exit 1
}
# shellcheck disable=SC1091
source "$HOME"/.openclaw/secrets/glm-coding-plan.env
[[ -n "${ZHIPU_API_KEY:-}" ]] || {
  printf 'Coding Plan credential is unavailable\n' >&2
  exit 1
}
api_key=$ZHIPU_API_KEY
keep=' HOME PATH USER LOGNAME LANG TERM TMPDIR TZ HTTPS_PROXY HTTP_PROXY NO_PROXY '
for name in $(compgen -e); do
  [[ $keep == *" $name "* ]] || unset -v "$name" 2>/dev/null || true
done
export ANTHROPIC_API_KEY="$api_key"
unset api_key
export ZCODE_MODEL=GLM-5.3 ZCODE_REVIEW_THOUGHT=max ZCODE_BASE_URL=https://open.bigmodel.cn/api/anthropic
read -r proc_stat 2>/dev/null </proc/$$/stat || proc_stat=
read -ra proc_fields <<<"${proc_stat##*) }"
printf 'reviewer pid=%s model=%s effort=%s started=%s proc_start=%s\n' \
  "$$" "$ZCODE_MODEL" "$ZCODE_REVIEW_THOUGHT" "$(TZ=Asia/Taipei date '+%Y-%m-%dT%H:%M:%S%:z')" "${proc_fields[19]:-}" >&2
# ZCode 0.16.3 help advertises --settings/--allowed-tools, but its parser rejects them.
# Native session/create enforces the allowlist; the protocol client verifies Max at runtime.
exec python3 "$script_dir/zcode-review.py" "$workdir" "$prompt_file" "$zcode_bin" </dev/null
