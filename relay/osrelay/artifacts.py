"""Filesystem and process facts; never infer business success from a PID."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone


class RelayError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="microseconds")


def git(workdir, *args):
    p = subprocess.run(["git", "-C", str(workdir), *args], capture_output=True)
    if p.returncode:
        raise RelayError("git_error", p.stderr.decode(errors="replace").strip())
    return p.stdout


def repo_root(path):
    return str(Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel")).rstrip("\n")).resolve())


def digest_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snapshot(workdir):
    """Same source fingerprint as osslab-manager evidence-run schema 2."""
    top = Path(repo_root(workdir))
    head = git(top, "rev-parse", "HEAD").decode().strip()
    diff = git(top, "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--binary", "--")
    files = []
    for name in git(top, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not name:
            continue
        relative = os.fsdecode(name)
        path = top / relative
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            digest = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
            kind = "symlink"
        elif stat.S_ISREG(mode):
            digest = digest_file(path)
            kind = "file"
        else:
            raise RelayError("unsupported_file", f"Untracked directory/special file: {relative}")
        files.append({"path": relative, "sha256": digest, "kind": kind, "mode": stat.S_IMODE(mode)})
    return {"head": head, "diff_head_sha256": hashlib.sha256(diff).hexdigest(), "untracked": files}


def untracked(workdir, path):
    """True when path is part of the snapshot's untracked set (not tracked, not ignored)."""
    return bool(git(workdir, "ls-files", "--others", "--exclude-standard", "-z", "--", str(path)))


def worktree_tree(workdir):
    """Tree a real commit of the current worktree would record.

    A throwaway GIT_INDEX_FILE stages HEAD plus tracked/untracked changes and
    deletions while the real index and worktree stay untouched. git's own clean
    filters and file modes apply, so the result matches an actual commit.
    """
    top = repo_root(workdir)
    base = git(top, "rev-parse", "HEAD").decode().strip()
    base_tree = git(top, "rev-parse", base + "^{tree}").decode().strip()
    holder = tempfile.mkdtemp(prefix="osrelay-tree-")
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = os.path.join(holder, "index")

    def run(*args):
        p = subprocess.run(["git", "-C", top, *args], capture_output=True, env=env)
        if p.returncode:
            raise RelayError("git_error", p.stderr.decode(errors="replace").strip())
        return p.stdout

    try:
        run("read-tree", base)
        run("add", "--all")
        tree = run("write-tree").decode().strip()
    finally:
        shutil.rmtree(holder, ignore_errors=True)
    return {"base": base, "base_tree": base_tree, "tree": tree}


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def identity(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "starttime": fields[19],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(record):
    return bool(record and identity(record["pid"]) == record)


def acquire_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RelayError("busy", f"Lock held: {path}") from None
    return fd


def worktree_lock(workdir):
    directory = Path(os.fsdecode(git(workdir, "rev-parse", "--absolute-git-dir")).rstrip("\n"))
    return acquire_lock(directory / "osrelay.lock")


def clean_env():
    allowed = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "TERM", "TMPDIR", "TZ",
               "XDG_RUNTIME_DIR", "DOCKER_HOST", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "ZCODE_CLI_BIN")
    return {key: os.environ[key] for key in allowed if key in os.environ}


def route(skill, engine):
    """Legacy helpers remain the only model-routing source."""
    names = {"pi": "pi-openrouter-worker.sh", "glm": "zcode-cloud-worker.sh",
             "grok": "grok-readonly-review.sh"}
    if engine not in names:
        raise RelayError("invalid_engine", engine)
    script = Path(skill) / "scripts" / names[engine]
    content = script.read_text()
    if engine == "glm":
        match = re.search(r"\bZCODE_MODEL=([\w./-]+)", content)
        effort = "helper-default"
    else:
        match = re.search(r"--model\s+([\w./-]+)", content)
        level = re.search(r"--(?:thinking|reasoning-effort)\s+([\w-]+)", content)
        effort = level.group(1) if level else "helper-default"
    if not match:
        raise RelayError("unknown_route", f"Cannot identify model in {script}")
    return {"engine": engine, "model": match.group(1), "effort": effort,
            "helper": names[engine], "sha256": digest_file(script)}
