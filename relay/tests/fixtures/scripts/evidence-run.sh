#!/usr/bin/env bash
set -euo pipefail

# CLI remains shell-compatible; Python handles both snapshots and the command result.
# Exit 125 means evidence capture failed or a passing command changed the worktree.
exec python3 - "$@" <<'PY'
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


def git(*args, cwd=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=check)


def now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")


def snapshot(top):
    if top is None:
        return {"head": None, "diff_head_sha256": None, "untracked": []}
    head = git("rev-parse", "HEAD", cwd=top).stdout.decode().strip()
    diff = git("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--binary", "--", cwd=top).stdout
    untracked = []
    names = git("ls-files", "--others", "--exclude-standard", "-z", cwd=top).stdout
    for name in names.split(b"\0"):
        if not name:
            continue
        relative = os.fsdecode(name)
        path = top / relative
        mode = path.lstat().st_mode
        digest = hashlib.sha256()
        if stat.S_ISLNK(mode):
            digest.update(os.fsencode(os.readlink(path)))
            kind = "symlink"
        elif stat.S_ISREG(mode):
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
            kind = "file"
        else:
            raise ValueError("unsupported untracked file type: " + relative)
        untracked.append({"path": relative, "sha256": digest.hexdigest(),
                          "kind": kind, "mode": stat.S_IMODE(mode)})
    return {"head": head, "diff_head_sha256": hashlib.sha256(diff).hexdigest(),
            "untracked": untracked}


def main():
    args = sys.argv[1:]
    if len(args) < 4 or args[2] != "--" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", args[1]):
        print("usage: evidence-run.sh <out-dir> <label> -- <command> [args...]", file=sys.stderr)
        return 2
    out, label, _, *argv = args
    out = Path(out).resolve()
    probe = git("rev-parse", "--show-toplevel", check=False)
    top = Path(os.fsdecode(probe.stdout).strip()).resolve() if probe.returncode == 0 else None
    if top is not None and (out == top or top in out.parents):
        if git("check-ignore", "-q", str(out), cwd=top, check=False).returncode != 0:
            print("out-dir is inside the work tree and not ignored; use the ticket state dir", file=sys.stderr)
            return 2
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    log, envelope = out / (label + ".log"), out / (label + ".json")
    if os.path.lexists(log) or os.path.lexists(envelope):
        print("evidence already exists; use a new label", file=sys.stderr)
        return 2
    # Exclusive create reserves the label even when two calls start together.
    try:
        stream = log.open("x", encoding="utf-8")
    except FileExistsError:
        print("evidence already exists; use a new label", file=sys.stderr)
        return 2
    rc = None
    try:
        with stream:
            before = snapshot(top)
            started = now()
            try:
                result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL)
                rc = result.returncode if result.returncode >= 0 else 128 - result.returncode
            except OSError as error:
                rc = 127 if isinstance(error, FileNotFoundError) else 126
                stream.write(str(error) + "\n")
            ended = now()
        after = snapshot(top)
        changed = before != after
        wrapper_exit = rc if rc else (125 if changed else 0)
        record = {"schema": 2, "cwd": os.getcwd(), "argv": argv, "exit_code": rc,
                  "wrapper_exit_code": wrapper_exit, "started": started, "ended": ended,
                  "before": before, "after": after, "worktree_changed": changed,
                  "verification_status": "worktree_changed" if changed else ("command_failed" if rc else "passed"),
                  "log": str(log), **after}
        # Keep schema-1 head/diff/untracked fields as aliases for the ending snapshot.
        with envelope.open("x", encoding="utf-8") as output:
            json.dump(record, output, ensure_ascii=True, indent=2)
            output.write("\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"evidence: failed to capture/write evidence: {error}; command_exit={rc}", file=sys.stderr)
        return rc if rc else 125
    print(f"evidence label={label} exit={rc} wrapper_exit={wrapper_exit} evidence=complete json={envelope} log={log}")
    if changed:
        print("evidence: worktree changed during command; inspect changes and rerun verification", file=sys.stderr)
    if wrapper_exit:
        with log.open(encoding="utf-8", errors="replace") as output:
            for line in collections.deque(output, maxlen=20):
                print(line, end="")
    return wrapper_exit


try:
    sys.exit(main())
except (OSError, ValueError, subprocess.SubprocessError) as error:
    print(f"evidence: failed before command: {error}", file=sys.stderr)
    sys.exit(125)
PY
