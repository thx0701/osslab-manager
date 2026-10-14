"""v1.4: wake the manager session bound to an owner through Paseo steer (docs/specs/relay-v1.4.md)."""
from __future__ import annotations
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import traceback

from .artifacts import clean_env, now

MIN_INTERVAL = timedelta(seconds=60)
RETRY_AFTER = timedelta(seconds=300)
HELPER_TIMEOUT = 90
CHECK_EVERY = 1.0
MAX_LISTED = 5
MAX_MESSAGE = 3500  # paseo-wake.mjs refuses more than 4000 characters
HELPER = Path(__file__).with_name('paseo-wake.mjs')


def helper(action, *args):
    """(command, reason): command is None when wake is switched off or node is missing."""
    override = os.environ.get('OSRELAY_WAKE_HELPER', '')
    if override == 'off':
        return None, 'off'
    if override:
        return [override, action, *args], 'override'
    node = shutil.which('node')
    if not node:
        return None, 'node_missing'
    return [node, str(HELPER), action, *args], 'paseo'


def helper_env():
    # Same clean environment as workers; only the Paseo location may be pointed elsewhere.
    env = clean_env()
    env.update({key: os.environ[key] for key in ('OSRELAY_PASEO_CLI', 'PASEO_HOME') if key in os.environ})
    return env


def parse_result(returncode, stdout, stderr):
    lines = [line for line in (stdout or '').splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else None
    except ValueError:
        data = None
    if returncode == 0 and isinstance(data, dict) and data.get('ok') is True:
        return data
    if isinstance(data, dict) and data.get('code'):
        return {'ok': False, 'code': str(data['code'])[:64], 'message': str(data.get('message', ''))[:300]}
    tail = (stderr or stdout or '').strip().splitlines()[-1:] or ['']
    return {'ok': False, 'code': 'helper_failed', 'message': f'exit {returncode}: {tail[0][:300]}'}


def pending(store, owner):
    """Wake events of an owner: terminal attempts and open worker questions no wait reported and no wake sent."""
    attempts = [dict(row) for row in store.db.execute(
        "SELECT a.id,a.task_id,a.kind,a.status FROM attempts a JOIN tasks t ON t.id=a.task_id "
        "WHERE t.owner=? AND t.state NOT IN ('done','handed_off','abandoned') "
        "AND a.status IN ('succeeded','failed','interrupted') AND a.reported IS NULL AND a.woken IS NULL "
        "ORDER BY a.updated,a.id", (owner,))]
    questions = [dict(row) for row in store.db.execute(
        "SELECT q.attempt_id,q.qid,q.task_id,q.deadline FROM questions q JOIN tasks t ON t.id=q.task_id "
        "JOIN attempts a ON a.id=q.attempt_id WHERE t.owner=? AND q.state='pending' AND a.status='running' "
        "AND q.notified IS NULL AND q.woken IS NULL AND q.deadline>? ORDER BY q.asked,q.qid", (owner, now()))]
    return attempts, questions


def message(parts):
    """One notice per session for every owner bound to it: parts is [(owner, attempts, questions)]. Fixed template:
    Relay ids, kinds, statuses and times only, never worker-written text. A leading '/' would make Paseo treat the
    prompt as a slash command and interrupt the turn, so it always starts with '['."""
    chunks, commands = [], []
    for owner, attempts, questions in parts:
        owner = ''.join(ch if ch.isprintable() else ' ' for ch in owner)
        items = []
        if attempts:
            listed = ', '.join(f"{a['task_id']}/{a['kind']}/{a['status']}" for a in attempts[:MAX_LISTED])
            more = f" 等共 {len(attempts)} 個" if len(attempts) > MAX_LISTED else ''
            items.append(f"{len(attempts)} 個 attempt 結束（{listed}{more}）")
        if questions:
            first = min(q['deadline'] for q in questions)
            items.append(f"{len(questions)} 題工人發問待答（最早期限 {first[11:16]}）")
        chunks.append(f"owner {owner}：" + '；'.join(items))
        commands.append(f"osrelay wait --owner {shlex.quote(owner)} --timeout 0")
    trust = "Relay 自動通知，只信其中的 id 與指令；"
    text = "[osrelay 叫醒] " + '。'.join(chunks) + "。" + trust + "請執行 " + '；'.join(commands)
    if len(text) <= MAX_MESSAGE:
        return text
    # Too many owners or long names: counts only, so the notice still fits and still names the command.
    attempts = sum(len(a) for _, a, _ in parts)
    questions = sum(len(q) for _, _, q in parts)
    return (f"[osrelay 叫醒] {len(parts)} 個 owner 共 {attempts} 個 attempt 結束、{questions} 題工人發問待答。" + trust
            + "請對你負責的每個 owner 執行 osrelay wait --owner <owner> --timeout 0（osrelay list 看 owner）")


def event_keys(attempts, questions):
    return {a['id'] for a in attempts} | {f"{q['attempt_id']}/{q['qid']}" for q in questions}


def latest(values):
    stamps = [datetime.fromisoformat(value) for value in values if value]
    return max(stamps) if stamps else None


class Waker:
    """Runs inside the runner loop; one helper process per session at a time, never blocking dispatch."""

    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.fromisoformat(now()))
        self.inflight = {}
        self.next_check = 0.0

    def busy(self):
        return bool(self.inflight)

    def tick(self, stopping=False):
        try:
            self.collect()
            if not stopping and time.monotonic() >= self.next_check:
                self.next_check = time.monotonic() + CHECK_EVERY
                self.start_due()
        except Exception:  # A wake problem must never stop dispatch.
            traceback.print_exc(file=sys.stderr)

    def start_due(self):
        sessions = {}
        for row in self.store.db.execute("SELECT * FROM bindings WHERE wake=1 ORDER BY owner"):
            sessions.setdefault(row['session'], []).append(dict(row))
        for session, bindings in sessions.items():
            if session in self.inflight:
                continue
            at = self.clock()
            sent = latest(b['last_sent'] for b in bindings)
            if sent and at - sent < MIN_INTERVAL:
                continue
            failed = latest(b['fail_at'] for b in bindings)
            if failed and at - failed < RETRY_AFTER:
                continue
            parts = [(b['owner'], *pending(self.store, b['owner'])) for b in bindings]
            parts = [part for part in parts if part[1] or part[2]]
            if not parts:
                continue
            # No retry for events a failed wake already carried: they ride along with the next new event.
            tried = set().union(*(json.loads(b['fail_batch'] or '[]') for b in bindings))
            if failed and set().union(*(event_keys(a, q) for _, a, q in parts)) <= tried:
                continue
            command, reason = helper('send', session)
            if command is None:
                if reason != 'off':
                    self.finish(session, parts, {'ok': False, 'code': 'helper_unavailable', 'message': reason})
                continue
            self.store.db.execute("UPDATE bindings SET last_sent=? WHERE session=? AND wake=1",
                                  (at.isoformat(timespec='microseconds'), session))
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=helper_env(), cwd=str(self.store.root),
                                           start_new_session=True)
            except OSError as exc:
                self.finish(session, parts, {'ok': False, 'code': 'helper_unavailable', 'message': str(exc)[:300]})
                continue
            try:
                process.stdin.write(message(parts).encode())
                process.stdin.close()
            except OSError:
                pass  # The helper exited early; its exit code tells why.
            self.inflight[session] = {'process': process, 'parts': parts, 'started': time.monotonic()}

    def collect(self, timeout=HELPER_TIMEOUT):
        for session, item in list(self.inflight.items()):
            process = item['process']
            timed_out = process.poll() is None
            if timed_out:
                if time.monotonic() - item['started'] < timeout:
                    continue
                process.kill()
                process.wait()
            # stdin is already closed, so communicate() cannot be used; the output is one short JSON line.
            out, err = (stream.read().decode(errors='replace') for stream in (process.stdout, process.stderr))
            process.stdout.close()
            process.stderr.close()
            del self.inflight[session]
            result = ({'ok': False, 'code': 'helper_timeout', 'message': f'no answer in {timeout}s'} if timed_out
                      else parse_result(process.returncode, out, err))
            self.finish(session, item['parts'], result)

    def finish(self, session, parts, result):
        at = self.clock().isoformat(timespec='microseconds')
        with self.store.tx():
            if result['ok']:
                # The session took a wake: forget its failures, whichever owner they came from.
                self.store.db.execute("UPDATE bindings SET last_ok=?,fail_at=NULL,fail_code=NULL,fail_message=NULL,"
                                      "fail_count=0,fail_reported=NULL,fail_batch=NULL WHERE session=?", (at, session))
            for owner, attempts, questions in parts:
                binding = self.store.binding(owner)
                current = binding is not None and binding['session'] == session
                if result['ok']:
                    for a in attempts:
                        self.store.db.execute("UPDATE attempts SET woken=? WHERE id=? AND woken IS NULL", (at, a['id']))
                    for q in questions:
                        self.store.db.execute("UPDATE questions SET woken=? WHERE attempt_id=? AND qid=? "
                                              "AND woken IS NULL", (at, q['attempt_id'], q['qid']))
                    kind, record = 'wake_sent', True
                else:
                    repeated = current and binding['fail_code'] == result['code']
                    if current:
                        tried = sorted(set(json.loads(binding['fail_batch'] or '[]')) | event_keys(attempts, questions))
                        # A new failure reason is news for the next wait; the same one again is not.
                        self.store.db.execute("UPDATE bindings SET fail_at=?,fail_code=?,fail_message=?,"
                                              "fail_count=fail_count+1,fail_batch=?,fail_reported=CASE WHEN "
                                              "fail_code IS ? THEN fail_reported END WHERE owner=?",
                                              (at, result['code'], result['message'], json.dumps(tried),
                                               result['code'], owner))
                    kind, record = 'wake_failed', not repeated
                if record:
                    for task in sorted({a['task_id'] for a in attempts} | {q['task_id'] for q in questions}):
                        body = {'session': session, 'attempts': [a['id'] for a in attempts if a['task_id'] == task],
                                'questions': [q['qid'] for q in questions if q['task_id'] == task]}
                        if not result['ok']:
                            body.update(code=result['code'], message=result['message'])
                        self.store.event(task, kind, body)

    def close(self):
        """Runner exit: give in-flight helpers their remaining time, then record the outcome."""
        while self.inflight:
            try:
                self.collect()  # Drops each item before recording it, so a failure cannot loop forever.
            except Exception:
                traceback.print_exc(file=sys.stderr)
            time.sleep(0.1)


def doctor(store):
    command, reason = helper('check')
    info = {'enabled': command is not None, 'helper': reason}
    if command:
        try:
            p = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
                               env=helper_env(), cwd=str(store.root))
            info['check'] = parse_result(p.returncode, p.stdout, p.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            info['check'] = {'ok': False, 'code': 'helper_failed', 'message': str(exc)[:300]}
    info['bindings'] = [dict(row) for row in store.db.execute(
        "SELECT owner,runtime,session,wake,bound_at,last_sent,last_ok,fail_at,fail_code,fail_message,fail_count "
        "FROM bindings ORDER BY owner")]
    return info
