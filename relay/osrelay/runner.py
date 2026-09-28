"""Durable dispatch intent, supervised children and conservative reconciliation."""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .artifacts import (RelayError, acquire_lock, worktree_lock, snapshot, now,
                        atomic_json, identity, alive, digest_file, clean_env)
from .store import Store, encode


def group_alive(record):
    """A dead supervisor can leave descendants; never recover underneath them."""
    if not record:
        return False
    if alive(record):
        return True
    if record['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        return False
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(') ', 1)[1].split()
            if (fields[0] != 'Z' and int(fields[3]) == record['pid']
                    and int(fields[19]) >= int(record['starttime'])):
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return False


def command_for(attempt, task):
    directory = Path(attempt['directory'])
    scripts = directory / 'skill/scripts'
    if attempt['kind'] == 'verify':
        return ['bash', str(scripts / 'evidence-run.sh'), str(directory / 'evidence'),
                'check', '--', *attempt['request']['command']]
    input_file = 'ticket.md' if attempt['kind'] == 'worker' else 'review-prompt.md'
    command = ['bash', str(scripts / attempt['route']['helper'])]
    session = attempt['request'].get('session') if attempt['kind'] == 'worker' else None
    if session:
        # A fresh run opens its own named session; a resume must continue it or be refused.
        command += ['--resume', session]
        if attempt['request'].get('resume'):
            command += ['--require-resume']
    command += [task['workdir'], str(directory / input_file)]
    return command


def child(state, aid, lock_fd):
    """Register before executing a helper; survive runner/session termination."""
    store = Store(state)
    attempt = store.attempt(aid)
    task = store.task(attempt['task_id'])
    directory = Path(attempt['directory'])
    with store.tx():
        updated = store.db.execute("UPDATE attempts SET status='running',process=?,updated=? WHERE id=? AND status='launching'",
                                   (encode(identity()), now(), aid)).rowcount
        if not updated:
            return 1  # recovery won the race; never execute stale dispatch intent
        store.event(task['id'], 'started', {'process': identity()}, aid)
    result = {'attempt': aid, 'exit_code': None, 'before': None, 'after': None,
              'proof': None, 'error': None, 'recovery': False}
    try:
        before = snapshot(task['workdir'])
        result['before'] = before
        if before != attempt['before_state']:
            raise RelayError('source_changed', 'Worktree changed between enqueue and start')
        with open(directory / 'stdout.log', 'xb') as stdout, open(directory / 'stderr.log', 'xb') as stderr:
            process = subprocess.Popen(command_for(attempt, task), cwd=task['workdir'],
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       env=clean_env(), pass_fds=(lock_fd,))
            result['exit_code'] = process.wait()
        result['after'] = snapshot(task['workdir'])
        changed = before != result['after']
        if attempt['kind'] != 'worker' and changed:
            raise RelayError('source_changed', 'Read-only review/verification changed the source')
        if (attempt['kind'] == 'worker' and attempt['request'].get('resume')
                and result['exit_code'] == 3 and not changed):
            # --require-resume refused before touching the tree: nothing to recover.
            raise RelayError('resume_refused', 'Helper refused to continue the session (exit 3)')
        if result['exit_code'] != 0:
            raise RelayError('command_failed', f"Helper exited {result['exit_code']}")
        proof = directory / ('receipt.md' if attempt['kind'] == 'worker' else
                             'stdout.log' if attempt['kind'] == 'review' else 'evidence/check.json')
        if not proof.is_file() or not proof.stat().st_size:
            raise RelayError('missing_proof', str(proof))
        if attempt['kind'] == 'verify':
            evidence = json.loads(proof.read_text())
            if (evidence.get('schema') != 2 or evidence.get('verification_status') != 'passed'
                    or evidence.get('wrapper_exit_code') != 0 or evidence.get('exit_code') != 0
                    or evidence.get('before') != before or evidence.get('after') != result['after']):
                raise RelayError('invalid_evidence', str(proof))
        result['proof'] = {'path': str(proof), 'sha256': digest_file(proof)}
    except Exception as exc:
        result['error'] = {'code': getattr(exc, 'code', 'execution_error'), 'message': str(exc)}
        # A failed worker may have partially edited files. A changed read-only
        # command also requires explicit recovery; never guess what to discard.
        refused = result['error']['code'] == 'resume_refused'
        result['recovery'] = ((attempt['kind'] == 'worker' and not refused)
                              or result['after'] is None or result['before'] != result['after'])
    result['completed'] = now()
    atomic_json(directory / 'result.json', result)
    store.close()
    return 0


def reconcile(store, skip=()):
    """Called only by the elected runner. Never re-execute ambiguous launches."""
    rows = store.db.execute("SELECT id FROM attempts WHERE status IN ('launching','running')").fetchall()
    for row in rows:
        if row[0] in skip:
            continue
        with store.tx():
            attempt = store.attempt(row[0])
            if group_alive(attempt['process']):
                continue
            path = Path(attempt['directory']) / 'result.json'
            result = None
            try:
                if path.exists():
                    result = json.loads(path.read_text())
                    if result.get('attempt') != attempt['id']:
                        raise ValueError('Result attempt mismatch')
                    if not result.get('error'):
                        proof = result['proof']
                        if digest_file(proof['path']) != proof['sha256']:
                            raise ValueError('Result proof changed')
            except (OSError, ValueError, KeyError, TypeError):
                result = None
            if result is None:
                status, task_state = 'interrupted', 'recovery_required'
                error = 'Process disappeared or launch outcome unknown; explicit recovery required'
            else:
                status = 'failed' if result['error'] else 'succeeded'
                task_state = 'recovery_required' if result['recovery'] else 'awaiting_acceptance'
                if (result['error'] or {}).get('code') == 'resume_refused' and not result['recovery']:
                    # Back to where the task was before this refused resume was queued.
                    queued = store.db.execute("SELECT body FROM events WHERE attempt_id=? AND kind='queued' "
                                              "ORDER BY seq LIMIT 1", (attempt['id'],)).fetchone()
                    task_state = json.loads(queued[0]).get('from', 'awaiting_acceptance') if queued else task_state
                error = encode(result['error']) if result['error'] else None
            store.db.execute('UPDATE attempts SET status=?,after_state=?,exit_code=?,error=?,updated=? WHERE id=?',
                             (status, encode(result['after']) if result and result['after'] else None,
                              result['exit_code'] if result else None, error, now(), attempt['id']))
            store.db.execute('UPDATE tasks SET state=?,updated=? WHERE id=?',
                             (task_state, now(), attempt['task_id']))
            store.event(attempt['task_id'], 'finished', {'status': status, 'result': result, 'error': error}, attempt['id'])


def dispatch(store, attempt_id):
    attempt = store.attempt(attempt_id)
    task = store.task(attempt['task_id'])
    try:
        lock_fd = worktree_lock(task['workdir'])
    except RelayError as exc:
        if exc.code == 'busy':
            return None
        raise
    try:
        with store.tx():
            if not store.db.execute("UPDATE attempts SET status='launching',updated=? WHERE id=? AND status='queued'",
                                    (now(), attempt_id)).rowcount:
                return None
            store.event(task['id'], 'launch_intent', {}, attempt_id)
        # Child registers itself with CAS before running any helper. If the
        # runner dies here, restart marks ambiguous launches for recovery.
        with open(Path(attempt['directory']) / 'supervisor.log', 'ab', buffering=0) as log:
            return subprocess.Popen([sys.executable, '-m', 'osrelay', '--state', str(store.root),
                                     '_child', attempt_id, str(lock_fd)],
                                    cwd=str(Path(__file__).resolve().parent.parent),
                                    env=clean_env(), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    pass_fds=(lock_fd,), start_new_session=True)
    finally:
        os.close(lock_fd)


def serve(store, interval=0.25):
    lock_fd = acquire_lock(store.root / 'runner.lock')
    stopping = False
    children = []

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        # Reconcile pre-existing records once before dispatch; skip our own
        # live unregistered children to avoid declaring their launch uncertain.
        reconcile(store)
        while True:
            children = [(aid, p) for aid, p in children if p.poll() is None]
            reconcile(store, {aid for aid, p in children})
            atomic_json(store.root / 'runner.json', {'process': identity(), 'heartbeat': now(), 'stopping': stopping})
            active = store.db.execute("SELECT 1 FROM attempts WHERE status IN ('launching','running') LIMIT 1").fetchone()
            if stopping and not children and not active:
                return
            if not stopping:
                rows = store.db.execute("SELECT id FROM attempts WHERE status='queued' ORDER BY created").fetchall()
                for row in rows:
                    process = dispatch(store, row[0])
                    if process:
                        children.append((row[0], process))
            time.sleep(interval)
    finally:
        os.close(lock_fd)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
