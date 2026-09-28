"""Transactional ownership and execution ledger (single Linux host)."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import uuid

from .artifacts import (RelayError, now, repo_root, snapshot, atomic_json, digest_file,
                        worktree_lock, worktree_tree, route, clean_env, untracked, git)

ACTIVE = ("queued", "launching", "running")
TERMINAL = ("succeeded", "failed", "interrupted", "canceled")
CLOSED = ("done", "handed_off", "abandoned")
LAUNCHED = ("succeeded", "failed", "interrupted")
SCHEMA_V2 = '''
  CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, note TEXT NOT NULL,
    created TEXT NOT NULL, updated TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, workdir TEXT NOT NULL, ticket TEXT NOT NULL,
    owner TEXT NOT NULL, state TEXT NOT NULL, parent TEXT REFERENCES tasks(id),
    runtime TEXT, session TEXT, blocked TEXT, note TEXT,
    goal_id TEXT, chain TEXT,
    created TEXT NOT NULL, updated TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS tasks_by_goal ON tasks(goal_id);
  CREATE TABLE IF NOT EXISTS reservations (
    workdir TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL REFERENCES tasks(id));
  CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    kind TEXT NOT NULL, request_key TEXT NOT NULL, request TEXT NOT NULL,
    status TEXT NOT NULL, directory TEXT NOT NULL, route TEXT NOT NULL,
    before_state TEXT NOT NULL, after_state TEXT, process TEXT,
    exit_code INTEGER, error TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
    UNIQUE(task_id, request_key));
  CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT REFERENCES tasks(id),
    attempt_id TEXT REFERENCES attempts(id), kind TEXT NOT NULL,
    body TEXT NOT NULL, at TEXT NOT NULL);
  PRAGMA user_version=2;
'''


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def same_request(stored, current):
    """v1 requests omit resume; a missing flag is a fresh run, not a different request."""
    left, right = dict(stored), dict(current)
    left["resume"] = bool(left.get("resume", False))
    right["resume"] = bool(right.get("resume", False))
    # chain (v1.2) and session are derived by Relay at enqueue time, not requested by the caller.
    for side in (left, right):
        side.pop("chain", None)
        side.pop("session", None)
    return left == right


def new_id(prefix):
    return prefix + "-" + uuid.uuid4().hex


def required(value, label):
    if not isinstance(value, str) or not value.strip():
        raise RelayError("missing_value", label + " is required")
    return value


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise RelayError("invalid_id", str(value))
    return value


class Store:
    def __init__(self, state):
        self.root = Path(state).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.db = sqlite3.connect(self.root / "relay.sqlite3", timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise RelayError("schema_version", f"Unsupported schema {version}")
        if version == 0:
            self.db.executescript(SCHEMA_V2)
        elif version == 1:
            self._upgrade_v1()

    def _upgrade_v1(self):
        """Add goal/chain columns. A v1 binary refuses user_version 2, so do not roll it back onto this file."""
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, note TEXT NOT NULL,
            created TEXT NOT NULL, updated TEXT NOT NULL);
        ''')
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(tasks)")}
        if "goal_id" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN goal_id TEXT")
        if "chain" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN chain TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS tasks_by_goal ON tasks(goal_id)")
        self.db.execute("PRAGMA user_version=2")

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def event(self, task, kind, body, attempt=None):
        self.db.execute("INSERT INTO events(task_id,attempt_id,kind,body,at) VALUES(?,?,?,?,?)",
                        (task, attempt, kind, encode(body), now()))

    def task(self, task_id, actor=None):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise RelayError("not_found", f"Task {task_id}")
        task = dict(row)
        if actor is not None and task["owner"] != actor:
            raise RelayError("owner_mismatch", f"Task belongs to {task['owner']}")
        return task

    def attempt(self, attempt_id):
        row = self.db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if not row:
            raise RelayError("not_found", f"Attempt {attempt_id}")
        result = dict(row)
        for key in ("request", "route", "before_state", "after_state", "process"):
            if result[key] is not None:
                result[key] = json.loads(result[key])
        return result

    def idle(self, task):
        if self.db.execute("SELECT 1 FROM attempts WHERE task_id=? AND status IN ('queued','launching','running')",
                           (task["id"],)).fetchone():
            raise RelayError("active_attempt", "Task still has active work")
        if task["state"] in CLOSED:
            raise RelayError("closed_task", task["state"])

    def create_goal(self, goal_id, owner, note):
        required(owner, "owner")
        required(note, "note")
        goal_id = valid_id(goal_id)
        with self.tx():
            if self.db.execute("SELECT 1 FROM tasks WHERE id=?", (goal_id,)).fetchone():
                raise RelayError("id_conflict", goal_id)
            old = self.db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            if old:
                if (old["owner"], old["note"]) == (owner, note):
                    return dict(old)
                raise RelayError("id_conflict", goal_id)
            at = now()
            self.db.execute("INSERT INTO goals(id,owner,note,created,updated) VALUES(?,?,?,?,?)",
                            (goal_id, owner, note, at, at))
        return dict(self.db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone())

    def is_goal(self, goal_id):
        goal = self.db.execute("SELECT 1 FROM goals WHERE id=?", (goal_id,)).fetchone()
        task = self.db.execute("SELECT 1 FROM tasks WHERE id=?", (goal_id,)).fetchone()
        if goal and task:
            raise RelayError("id_conflict", goal_id)
        return bool(goal)

    def create(self, workdir, ticket, owner, task_id=None, goal=None, chain=None):
        required(owner, "owner")
        workdir = repo_root(workdir)
        if self.root.is_relative_to(Path(workdir)):
            raise RelayError("state_inside_worktree", "Relay state must be outside the worktree")
        path = Path(ticket).resolve(strict=True)
        if not path.is_file():
            raise RelayError("invalid_ticket", "Ticket must be a file")
        outside_fingerprint(workdir, path, "ticket")
        task_id = valid_id(task_id or new_id("task"))
        if goal is not None:
            goal = valid_id(goal)
            chain = valid_id(required(chain, "chain"))
        elif chain is not None:
            chain = valid_id(chain)
        with self.tx():
            if goal and not self.db.execute("SELECT 1 FROM goals WHERE id=?", (goal,)).fetchone():
                raise RelayError("not_found", f"Goal {goal}")
            if self.db.execute("SELECT 1 FROM goals WHERE id=?", (task_id,)).fetchone():
                raise RelayError("id_conflict", task_id)
            old = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if old:
                if (old["workdir"], old["ticket"], old["owner"], old["goal_id"], old["chain"]) == (
                        workdir, str(path), owner, goal, chain):
                    return dict(old)
                raise RelayError("id_conflict", task_id)
            at = now()
            self.db.execute(
                "INSERT INTO tasks(id,workdir,ticket,owner,state,goal_id,chain,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                (task_id, workdir, str(path), owner, "ready", goal, chain, at, at))
            self.event(task_id, "created", {"owner": owner, "goal": goal, "chain": chain})
        return self.task(task_id)

    def status(self, task_id):
        task = self.task(task_id)
        task["blocked"] = json.loads(task["blocked"]) if task["blocked"] else None
        task["attempts"] = [self.attempt(row[0]) for row in self.db.execute(
            "SELECT id FROM attempts WHERE task_id=? ORDER BY created,id", (task_id,)).fetchall()]
        task["events"] = [dict(row) for row in self.db.execute(
            "SELECT * FROM events WHERE task_id=? ORDER BY seq", (task_id,))]
        for event in task["events"]:
            event["body"] = json.loads(event["body"])
        return task

    def bind(self, task_id, actor, runtime, session):
        if runtime not in ("codex", "claude"):
            raise RelayError("runtime", "Supported manager runtimes: codex, claude")
        with self.tx():
            self.task(task_id, actor)
            self.db.execute("UPDATE tasks SET runtime=?,session=?,updated=? WHERE id=?",
                            (runtime, required(session, "session"), now(), task_id))
            self.event(task_id, "manager_bound", {"runtime": runtime, "session": session, "owner": actor})
        return self.status(task_id)

    def block(self, task_id, actor, reason, resume_note, wake_condition):
        block = {"reason": required(reason, "reason"), "resume_note": required(resume_note, "resume_note"),
                 "wake_condition": required(wake_condition, "wake_condition")}
        with self.tx():
            task = self.task(task_id, actor)
            self.idle(task)
            if task["state"] == "recovery_required":
                raise RelayError("recovery_required", "Recover before parking")
            if task["state"] == "accepted":
                raise RelayError("invalid_state", "Accepted task waits for finalize or abandon; block refused")
            self.db.execute("UPDATE tasks SET state='blocked',blocked=?,updated=? WHERE id=?",
                            (encode(block), now(), task_id))
            self.event(task_id, "blocked", block)
        return self.status(task_id)

    def unblock(self, task_id, actor, note):
        required(note, "note")
        with self.tx():
            task = self.task(task_id, actor)
            if task["state"] != "blocked":
                raise RelayError("invalid_state", "Task is not blocked")
            self.db.execute("UPDATE tasks SET state='ready',blocked=NULL,note=?,updated=? WHERE id=?",
                            (note, now(), task_id))
            self.event(task_id, "unblocked", {"note": note})
        return self.status(task_id)

    def handoff(self, task_id, actor, destination, key, note):
        required(destination, "destination"); required(key, "key"); required(note, "note")
        successor = "task-" + hashlib.sha256((task_id + "\0" + key).encode()).hexdigest()[:32]
        with self.tx():
            task = self.task(task_id, actor)
            old = self.db.execute("SELECT * FROM tasks WHERE id=?", (successor,)).fetchone()
            if old:
                received = self.db.execute("SELECT body FROM events WHERE task_id=? AND kind='received' ORDER BY seq LIMIT 1",
                                           (successor,)).fetchone()
                original = json.loads(received[0]) if received else {}
                if (old["parent"] == task_id and old["owner"] == destination
                        and original.get("key") == key and original.get("note") == note):
                    return self.status(successor)
                raise RelayError("idempotency_conflict", key)
            self.idle(task)
            if task["state"] == "recovery_required":
                raise RelayError("recovery_required", "Recover before handing off")
            if task["state"] == "accepted":
                raise RelayError("invalid_state", "Accepted task waits for finalize or abandon; handoff refused")
            at = now()
            state = "blocked" if task["state"] == "blocked" else "ready"
            self.db.execute(
                "INSERT INTO tasks(id,workdir,ticket,owner,state,parent,blocked,note,goal_id,chain,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (successor, task["workdir"], task["ticket"], destination, state, task_id,
                 task["blocked"], note, task["goal_id"], task["chain"], at, at))
            self.db.execute("UPDATE tasks SET state='handed_off',updated=? WHERE id=?", (at, task_id))
            self.db.execute("UPDATE reservations SET task_id=? WHERE task_id=?", (successor, task_id))
            self.event(task_id, "handed_off", {"to": successor, "owner": destination, "key": key, "note": note})
            self.event(successor, "received", {"from": task_id, "owner": actor, "key": key, "note": note})
        return self.status(successor)

    def enqueue(self, task_id, actor, key, kind, skill, engine=None, prompt=None, command=None, note=None, resume=False):
        required(key, "key")
        skill = Path(skill).expanduser().resolve(strict=True)
        engine = engine or ("grok" if kind == "review" else "pi")
        if kind == "worker" and engine not in ("pi", "glm"):
            raise RelayError("invalid_engine", "worker must be pi or glm")
        if resume and (kind != "worker" or engine != "pi"):
            raise RelayError("resume_refused", "Resume is only for the pi worker")
        if kind == "review" and engine != "grok":
            raise RelayError("invalid_engine", "routine review uses skill's Grok helper")
        if kind == "verify" and not command:
            raise RelayError("missing_command", "verify needs -- command arguments")
        if kind == "review" and not prompt:
            raise RelayError("missing_prompt", "review needs a prompt file")
        if prompt:
            task_row = self.task(task_id)
            outside_fingerprint(task_row["workdir"], Path(prompt).resolve(strict=True), "review prompt")
        prompt_text = Path(prompt).read_text() if prompt else None
        request = {"kind": kind, "engine": engine if kind != "verify" else None,
                   "skill": str(skill), "prompt": prompt_text, "command": command, "note": note,
                   "resume": bool(resume)}
        with self.tx():
            task = self.task(task_id, actor)
            old = self.db.execute("SELECT id,request FROM attempts WHERE task_id=? AND request_key=?", (task_id, key)).fetchone()
            if old:
                if same_request(json.loads(old["request"]), request):
                    return self.attempt(old["id"])
                raise RelayError("idempotency_conflict", key)
            if resume:
                request["session"] = self._assert_resume(task)
            self.idle(task)
            if task["state"] not in ("ready", "awaiting_acceptance"):
                raise RelayError("invalid_state", task["state"])
            reservation = self.db.execute("SELECT task_id FROM reservations WHERE workdir=?", (task["workdir"],)).fetchone()
            if reservation and reservation[0] != task_id:
                raise RelayError("worktree_reserved", f"Reserved by {reservation[0]}")
            aid = new_id("attempt")
            if kind == "worker" and engine == "pi" and not resume:
                # Every pi worker opens its own named session, so a later --resume has one to continue.
                request["session"] = aid
            directory = self.root / "attempts" / aid
            directory.mkdir(mode=0o700, parents=True)
            # This is a trusted, explicitly selected installed skill, not downloaded code.
            shutil.copytree(skill, directory / "skill", symlinks=False)
            info = route(directory / "skill", engine) if kind != "verify" else {"engine": "verify", "helper": "evidence-run.sh"}
            ticket = Path(task["ticket"]).read_text()
            (directory / "ticket.original.md").write_text(ticket)
            receipt = directory / "receipt.md"
            if resume:
                continuity = f"此輪接續本單 pi session {request['session']}。記憶不是證據，以工單與目前檔案為準。"
            else:
                continuity = "此輪從零開始，不沿用先前 session。"
            ticket += f"\n\n## Relay 本輪執行契約\n本輪回執唯一指定路徑：{receipt}\n原工單留在原處，不改寫、不挪動。{continuity}\n"
            (directory / "ticket.md").write_text(ticket)
            if prompt_text is not None:
                (directory / "review-prompt.md").write_text(prompt_text)
            before = snapshot(task["workdir"])
            at = now()
            self.db.execute("INSERT INTO attempts(id,task_id,kind,request_key,request,status,directory,route,before_state,created,updated) VALUES(?,?,?,?,?,'queued',?,?,?,?,?)",
                            (aid, task_id, kind, key, encode(request), str(directory), encode(info), encode(before), at, at))
            self.db.execute("INSERT OR IGNORE INTO reservations(workdir,task_id) VALUES(?,?)", (task["workdir"], task_id))
            self.db.execute("UPDATE tasks SET state='running',updated=? WHERE id=?", (at, task_id))
            self.event(task_id, "queued", {"kind": kind, "route": info, "actor": actor, "from": task["state"]}, aid)
            atomic_json(directory / "manifest.json", {"attempt": aid, "task": task_id, "workdir": task["workdir"],
                                                       "route": info, "request": request, "before": before})
        return self.attempt(aid)

    def cancel(self, attempt_id, actor, note):
        required(note, "note")
        with self.tx():
            attempt = self.attempt(attempt_id)
            self.task(attempt["task_id"], actor)
            if attempt["status"] != "queued":
                raise RelayError("invalid_state", "Only queued attempts can be canceled; no automatic process killing")
            # Return to the state before this attempt was queued: canceling a queued
            # verify/review must not drop a finished worker out of awaiting_acceptance.
            queued = self.db.execute("SELECT body FROM events WHERE attempt_id=? AND kind='queued' ORDER BY seq LIMIT 1",
                                     (attempt_id,)).fetchone()
            previous = json.loads(queued[0]).get("from", "ready") if queued else "ready"
            self.db.execute("UPDATE attempts SET status='canceled',updated=?,error=? WHERE id=?", (now(), note, attempt_id))
            self.db.execute("UPDATE tasks SET state=?,updated=? WHERE id=?", (previous, now(), attempt["task_id"]))
            self.event(attempt["task_id"], "canceled", {"note": note}, attempt_id)
        return self.attempt(attempt_id)

    def recover(self, task_id, actor, note):
        required(note, "inheritance note")
        task = self.task(task_id, actor)
        self.idle(task)
        if task["state"] != "recovery_required":
            raise RelayError("invalid_state", "Task does not need recovery")
        fd = worktree_lock(task["workdir"])
        try:
            with self.tx():
                task = self.task(task_id, actor)
                self.idle(task)
                if task["state"] != "recovery_required":
                    raise RelayError("invalid_state", "Task no longer needs recovery")
                last = self.db.execute("SELECT id FROM attempts WHERE task_id=? ORDER BY created DESC LIMIT 1", (task_id,)).fetchone()
                attempt = self.attempt(last[0])
                from .runner import group_alive
                if group_alive(attempt["process"]):
                    raise RelayError("process_alive", "Supervisor or its descendants still run")
            # Keep the worktree lock, not SQLite's global write lock, throughout
            # potentially long backups. Other tasks must remain operable.
            directory = Path(attempt["directory"])
            bundle = directory / ("recovery-" + uuid.uuid4().hex)
            script = directory / "skill/scripts/backup-worktree.sh"
            result = subprocess.run(["bash", str(script), task["workdir"], str(bundle)],
                                    capture_output=True, env=clean_env(), stdin=subprocess.DEVNULL,
                                    pass_fds=(fd,))
            (directory / (bundle.name + ".log")).write_bytes(result.stdout + result.stderr)
            if result.returncode or not (bundle / "SHA256SUMS").is_file():
                raise RelayError("backup_failed", f"Source unchanged; inspect {bundle}")
            with self.tx():
                current = self.task(task_id, actor)
                self.idle(current)
                if current["state"] != "recovery_required":
                    raise RelayError("invalid_state", "Task changed during recovery; backup retained")
                self.db.execute("UPDATE tasks SET state='ready',note=?,updated=? WHERE id=?", (note, now(), task_id))
                self.event(task_id, "recovered", {"bundle": str(bundle), "resolution": "inherit", "note": note}, attempt["id"])
        finally:
            os.close(fd)
        return self.status(task_id)

    def proof(self, attempt, current):
        """Latest evidence must pass on the current source and still match what was collected."""
        kind = attempt["kind"]
        if attempt["status"] != "succeeded" or attempt["after_state"] != current:
            raise RelayError("stale_evidence", kind + " must pass on current version")
        path = Path(attempt["directory"]) / ("evidence/check.json" if kind == "verify" else "stdout.log")
        if not path.is_file() or not path.stat().st_size:
            raise RelayError("missing_evidence", str(path))
        finished = self.db.execute("SELECT body FROM events WHERE attempt_id=? AND kind='finished' ORDER BY seq DESC LIMIT 1",
                                   (attempt["id"],)).fetchone()
        collected = json.loads(finished[0]).get("result") if finished else None
        expected = {"path": str(path), "sha256": digest_file(path)}
        if not collected or collected.get("proof") != expected:
            raise RelayError("changed_evidence", kind + " proof changed since collection")
        return {"attempt": attempt["id"], "path": str(path), "sha256": expected["sha256"]}

    def accept(self, task_id, actor, note, review_waiver=None):
        required(note, "manager review/acceptance note")
        if review_waiver is not None:
            required(review_waiver, "review waiver reason")
        with self.tx():
            task = self.task(task_id, actor)
            self.idle(task)
            if task["state"] != "awaiting_acceptance":
                raise RelayError("invalid_state", task["state"])
            fd = worktree_lock(task["workdir"])
            try:
                current = snapshot(task["workdir"])
                # Every distinct command ever verified must pass again on the current
                # version: a later passing command cannot hide an earlier failing one.
                latest = {}
                for row in self.db.execute("SELECT id FROM attempts WHERE task_id=? AND kind='verify' ORDER BY created,id",
                                           (task_id,)).fetchall():
                    attempt = self.attempt(row[0])
                    latest[encode(attempt["request"]["command"])] = attempt
                if not latest:
                    raise RelayError("missing_evidence", "verify")
                evidence = {"verify": [self.proof(attempt, current) for attempt in latest.values()]}
                # A review canceled while queued never ran: it neither raises the tier nor counts as evidence.
                reviews = self.db.execute("SELECT id FROM attempts WHERE task_id=? AND kind='review' AND status!='canceled' "
                                          "ORDER BY created DESC,id DESC",
                                          (task_id,)).fetchall()
                if review_waiver is not None:
                    # Review tier only goes up: once a review ran, it cannot be waived.
                    if reviews:
                        raise RelayError("review_required", "A review already ran for this task; it cannot be waived")
                    evidence["review"] = {"waived": review_waiver}
                elif not reviews:
                    raise RelayError("missing_evidence", "review")
                else:
                    evidence["review"] = self.proof(self.attempt(reviews[0][0]), current)
                accepted = worktree_tree(task["workdir"])
                if snapshot(task["workdir"]) != current:
                    raise RelayError("source_changed", "Worktree changed while recording the accepted tree")
                self.db.execute("UPDATE tasks SET state='accepted',note=?,updated=? WHERE id=?", (note, now(), task_id))
                self.event(task_id, "accepted", {"actor": actor, "note": note, "evidence": evidence,
                                                 "base": accepted["base"], "base_tree": accepted["base_tree"],
                                                 "tree": accepted["tree"]})
            finally:
                os.close(fd)
        return self.status(task_id)

    def resolve_commit(self, workdir, value):
        try:
            return git(workdir, "rev-parse", "--verify", value + "^{commit}").decode().strip()
        except RelayError:
            raise RelayError("unknown_commit", f"Cannot resolve commit {value}") from None

    def finalize(self, task_id, actor, commit_sha, note):
        """Close an accepted task after the manager's own commit matches the accepted tree."""
        required(note, "finalize note")
        required(commit_sha, "commit SHA")
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise RelayError("invalid_commit", "commit must be a hex SHA")
        with self.tx():
            task = self.task(task_id, actor)
            if task["state"] == "done":
                event = self.db.execute("SELECT body FROM events WHERE task_id=? AND kind='finalized' "
                                        "ORDER BY seq DESC LIMIT 1", (task_id,)).fetchone()
                if not event:
                    raise RelayError("invalid_state", "Task was already done without a finalize record")
                if json.loads(event[0]).get("commit") == self.resolve_commit(task["workdir"], commit_sha):
                    return self.status(task_id)
                raise RelayError("commit_mismatch", "Task is already finalized with a different commit")
            self.idle(task)
            if task["state"] != "accepted":
                raise RelayError("invalid_state", task["state"])
            event = self.db.execute("SELECT body FROM events WHERE task_id=? AND kind='accepted' "
                                    "ORDER BY seq DESC LIMIT 1", (task_id,)).fetchone()
            if not event:
                raise RelayError("invalid_state", "No accepted tree recorded")
            record = json.loads(event[0])
            base, tree = record["base"], record["tree"]
            fd = worktree_lock(task["workdir"])
            try:
                current = snapshot(task["workdir"])
                if current["diff_head_sha256"] != hashlib.sha256(b"").hexdigest() or current["untracked"]:
                    raise RelayError("dirty_worktree", "Commit or clean the worktree before finalize")
                # git diff HEAD compares the worktree with HEAD; a staged change whose
                # worktree change cancels it (MM/AD) stays invisible. The index must
                # match HEAD too, or finalize would release the lock on a stale tree.
                if git(task["workdir"], "diff", "--no-ext-diff", "--no-textconv", "--cached", "HEAD", "--"):
                    raise RelayError("dirty_worktree", "Index differs from HEAD; reset or commit it before finalize")
                commit = self.resolve_commit(task["workdir"], commit_sha)
                if commit != current["head"]:
                    raise RelayError("head_mismatch", "commit is not the current HEAD")
                committed_tree = git(task["workdir"], "rev-parse", commit + "^{tree}").decode().strip()
                if committed_tree != tree:
                    raise RelayError("tree_mismatch", "committed tree differs from the accepted tree")
                if commit == base:
                    if tree != record.get("base_tree"):
                        raise RelayError("history_mismatch", "Base HEAD may close only a no-change acceptance")
                else:
                    parents = git(task["workdir"], "rev-list", "--parents", "-n", "1", commit).decode().split()
                    if len(parents) != 2 or parents[1] != base:
                        raise RelayError("history_mismatch", "commit must be a single-parent child of the accepted base")
                self.db.execute("UPDATE tasks SET state='done',note=?,updated=? WHERE id=?", (note, now(), task_id))
                self.db.execute("DELETE FROM reservations WHERE task_id=?", (task_id,))
                self.event(task_id, "finalized", {"actor": actor, "note": note, "commit": commit,
                                                  "tree": committed_tree, "base": base})
            finally:
                os.close(fd)
        return self.status(task_id)

    def abandon(self, task_id, actor, note):
        """Close without acceptance and release the worktree; never touches source files."""
        required(note, "abandon note")
        with self.tx():
            task = self.task(task_id, actor)
            self.idle(task)
            if task["state"] == "recovery_required":
                raise RelayError("recovery_required", "Recover (backup) before abandoning")
            self.db.execute("UPDATE tasks SET state='abandoned',note=?,updated=? WHERE id=?", (note, now(), task_id))
            self.db.execute("DELETE FROM reservations WHERE task_id=?", (task_id,))
            self.event(task_id, "abandoned", {"actor": actor, "note": note, "from": task["state"]})
        return self.status(task_id)

    def _assert_resume(self, task):
        """Refuse a resume the helper could not honor; return the session to continue.

        The session belongs to this task (its latest succeeded pi worker), not to the
        worktree chain: a commit on the chain moves HEAD and ends every session anyway.
        Called inside the enqueue transaction.
        """
        if self.db.execute("SELECT 1 FROM events WHERE task_id=? AND kind='recovered'", (task["id"],)).fetchone():
            raise RelayError("resume_refused", "Recovered task starts fresh")
        launched = []
        for row in self.db.execute("SELECT id FROM attempts WHERE task_id=? AND kind='worker' ORDER BY created,id",
                                   (task["id"],)):
            attempt = self.attempt(row[0])
            if attempt["status"] in LAUNCHED:
                launched.append(attempt)
        succeeded = [item for item in launched if item["status"] == "succeeded"]
        if not succeeded:
            raise RelayError("resume_refused", "No previous succeeded worker to continue")
        latest = succeeded[-1]
        session = latest["request"].get("session")
        if not session or latest["request"].get("engine") != "pi":
            raise RelayError("resume_refused", "Previous succeeded worker left no pi session")
        users = [item for item in launched if item["request"].get("session") == session]
        # A resume the helper refused (exit 3, tree untouched) never continued the session.
        used = [item for item in users if item["request"].get("resume") and not refused_resume(item)]
        if len(used) >= 2:
            raise RelayError("resume_refused", "Resume limit 2 reached")
        origin = users[0]
        original = Path(origin["directory"]) / "ticket.original.md"
        if not original.is_file() or original.read_text() != Path(task["ticket"]).read_text():
            raise RelayError("resume_refused", "Ticket changed since the session started")
        if snapshot(task["workdir"])["head"] != origin["before_state"]["head"]:
            raise RelayError("resume_refused", "HEAD changed since the session started")
        if receipt_has_doubt(Path(latest["directory"]) / "receipt.md"):
            raise RelayError("resume_refused", "Previous receipt has unresolved doubts")
        if not pi_session_exists(session, task["workdir"]):
            raise RelayError("resume_refused", "Pi session file is missing")
        return session

    def goal_context(self, goal_id, runtime):
        row = self.db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        if not row:
            raise RelayError("not_found", f"Goal {goal_id}")
        goal = dict(row)
        children = [self._child_view(item[0]) for item in self.db.execute(
            "SELECT id FROM tasks WHERE goal_id=? ORDER BY created,id", (goal_id,))]
        return {"kind": "goal", "id": goal["id"], "owner": goal["owner"], "note": goal["note"],
                "created": goal["created"], "updated": goal["updated"], "requested_runtime": runtime,
                "children": children,
                "next_step": "Read each child's receipt and evidence. A frozen chain's review may run while "
                             "another chain builds on a different worktree."}

    def _child_view(self, task_id):
        task = self.task(task_id)
        view = {"id": task["id"], "owner": task["owner"], "state": task["state"], "chain": task["chain"],
                "workdir": task["workdir"], "parent": task["parent"], "receipt": None, "verify": [], "review": None}
        workers, verifies, reviews = [], [], []
        for row in self.db.execute("SELECT id FROM attempts WHERE task_id=? ORDER BY created,id", (task_id,)):
            attempt = self.attempt(row[0])
            if attempt["kind"] == "worker":
                workers.append(attempt)
            elif attempt["kind"] == "verify":
                verifies.append(attempt)
            elif attempt["kind"] == "review" and attempt["status"] != "canceled":
                reviews.append(attempt)
        succeeded = [item for item in workers if item["status"] == "succeeded"]
        if succeeded:
            receipt = Path(succeeded[-1]["directory"]) / "receipt.md"
            view["receipt"] = {"attempt": succeeded[-1]["id"], "path": str(receipt),
                               "sha256": digest_file(receipt) if receipt.is_file() else None}
        latest = {}
        for attempt in verifies:
            latest[encode(attempt["request"]["command"])] = attempt
        view["verify"] = [evidence_file(attempt, "evidence/check.json") for attempt in latest.values()]
        if reviews:
            view["review"] = evidence_file(reviews[-1], "stdout.log")
        return view


def refused_resume(attempt):
    try:
        return json.loads(attempt["error"] or "{}").get("code") == "resume_refused"
    except (TypeError, ValueError):
        return False


def receipt_has_doubt(path):
    """True when section 4 exists and is neither empty nor 無. A receipt without the section is not a doubt."""
    if not path.is_file():
        return True
    text = path.read_text()
    marker = "## 4. 風險與存疑"
    if marker not in text:
        return False
    body = text.split(marker, 1)[1]
    nxt = body.find("\n## ")
    if nxt != -1:
        body = body[:nxt]
    return body.strip() not in ("", "無")


def pi_session_exists(session, workdir):
    digest = hashlib.sha256(workdir.encode()).hexdigest()[:12]
    directory = Path.home() / ".local/state/osslab-manager/pi-sessions" / f"{session}-{digest}"
    return any(path.is_file() for path in directory.glob(f"*_{session}.jsonl"))


def evidence_file(attempt, name):
    path = Path(attempt["directory"]) / name
    item = {"attempt": attempt["id"], "status": attempt["status"], "command": attempt["request"].get("command"),
            "head": attempt["after_state"].get("head") if isinstance(attempt["after_state"], dict) else None}
    if path.is_file() and path.stat().st_size:
        item["path"] = str(path)
        item["sha256"] = digest_file(path)
    return item


def outside_fingerprint(workdir, path, label):
    """Untracked, non-ignored files inside the worktree change the source fingerprint."""
    if Path(workdir) in path.parents and untracked(workdir, path):
        raise RelayError("inside_worktree", f"{label} {path} is an untracked, non-ignored file in the worktree; "
                         "keep it outside, git-ignore it, or commit it")
