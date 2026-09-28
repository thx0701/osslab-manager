#!/usr/bin/env bash
set -euo pipefail

# Read-only recovery bundle. Never resets, cleans, or restores the source worktree.
# Captures working contents relative to HEAD, not the staged/unstaged distinction.
[[ $# -eq 2 ]] || { echo 'usage: backup-worktree.sh <workdir> <new-out-dir>' >&2; exit 2; }
workdir=$(git -C "$1" rev-parse --show-toplevel)
workdir=$(readlink -f "$workdir")
out=$(readlink -m "$2")
[[ $out != "$workdir" && $out != "$workdir"/* ]] || {
  echo 'backup must be outside the worktree' >&2; exit 2;
}
# mkdir without -p refuses existing bundles, including a previous failed attempt.
umask 077
mkdir "$out"
cd "$workdir"
git rev-parse --verify HEAD >"$out/base-head"
# A superproject patch cannot preserve a submodule's uncommitted contents.
if git ls-files --stage | grep '^160000 ' >/dev/null; then
  echo 'submodules require separate recovery; bundle incomplete' >&2; exit 2
fi
git diff --no-ext-diff --no-textconv --binary HEAD -- >"$out/tracked.patch"
git ls-files --others --exclude-standard -z >"$out/untracked.list"
while IFS= read -r -d '' path; do
  if [[ -d $path && ! -L $path ]] || [[ ! -f $path && ! -L $path ]]; then
    echo 'unsupported untracked directory or special file; bundle incomplete' >&2; exit 2
  fi
done <"$out/untracked.list"
tar --create --file="$out/untracked.tar" --null --verbatim-files-from --no-recursion --files-from="$out/untracked.list"
# Check the saved artifacts against the stopped worker's current contents.
tar --compare --file="$out/untracked.tar"
if [[ -s $out/tracked.patch ]]; then
  git apply --reverse --check "$out/tracked.patch"
fi
git rev-parse HEAD | cmp -s "$out/base-head" -
git diff --no-ext-diff --no-textconv --binary HEAD -- | cmp -s "$out/tracked.patch" -
git ls-files --others --exclude-standard -z | cmp -s "$out/untracked.list" -
(cd "$out" && sha256sum base-head tracked.patch untracked.list untracked.tar >SHA256SUMS)
printf 'backup verified: %s (ignored files and index staging excluded)\n' "$out"
