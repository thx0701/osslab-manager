"""Public CLI regression on real Git/SQLite/processes; no paid model calls."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, '-m', 'osrelay']


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='relay-test-')
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.state = self.base / 'state'
        self.ticket = self.base / 'ticket.md'
        self.started = self.base / 'started'
        self.skill = self.base / 'skill'
        shutil.copytree(ROOT / 'tests/fixtures', self.skill)
        for args in [('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid')]:
            subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)
        (self.repo / 'source.txt').write_text('initial\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'fixture'], check=True)
        self.write_ticket()
        self.runners = []
        self.logs = []
        # Pi sessions live under $HOME; never touch the real one.
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home))

    def tearDown(self):
        (self.base / 'gate').touch()
        for p in self.runners:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
        for log in self.logs:
            log.close()
        self.temp.cleanup()

    def call(self, *args, error=None):
        p = subprocess.run([*CLI, '--state', str(self.state), *map(str, args)], cwd=ROOT,
                           capture_output=True, text=True, timeout=20, env=self.env)
        try:
            data = json.loads(p.stderr if p.returncode else p.stdout)
        except Exception:
            self.fail(f'{args}: {p.returncode}\n{p.stdout}\n{p.stderr}')
        if error:
            self.assertNotEqual(p.returncode, 0, data)
            self.assertEqual(data['error']['code'], error, data)
            return data
        self.assertEqual(p.returncode, 0, data)
        return data['result']

    def write_ticket(self, **options):
        options['started'] = str(self.started)
        self.ticket.write_text(json.dumps(options) + '\nDo the fixture task.\n')

    def create(self, name='t1', owner='manager'):
        return self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', owner, '--id', name)

    def enqueue(self, kind='run', key='one', task='t1', owner='manager', **kwargs):
        args = [kind, task, '--owner', owner, '--key', key, '--skill', self.skill]
        if kind == 'run' and kwargs.get('engine'):
            args += ['--engine', kwargs['engine']]
        if kind == 'run' and kwargs.get('resume'):
            args.append('--resume')
        if kind == 'review':
            prompt = self.base / 'review.md'
            prompt.write_text(kwargs.get('prompt', 'review'))
            args += ['--prompt', prompt]
        if kind == 'verify':
            args += ['--', sys.executable, '-c', kwargs.get('command', "assert open('source.txt').read() == 'edited\\n'")]
        return self.call(*args, error=kwargs.get('error'))

    def runner(self):
        log = open(self.base / f'runner-{len(self.runners)}.log', 'wb')
        self.logs.append(log)
        p = subprocess.Popen([*CLI, '--state', str(self.state), 'serve'], cwd=ROOT,
                             stdout=log, stderr=log, env=self.env)
        self.runners.append(p)
        return p

    def eventually(self, callback, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            value = callback()
            if value:
                return value
            time.sleep(.05)
        self.fail('Timed out waiting for fixture condition')

    def completed(self, aid):
        return self.call('wait', aid, '--timeout', '8')

    def success_worker(self):
        self.write_ticket(edit='edited\n')
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        return attempt

    def commit_repo(self, message='accept commit'):
        subprocess.run(['git', '-C', str(self.repo), 'add', '-A'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', message], check=True, capture_output=True)
        return subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], check=True,
                              capture_output=True, text=True).stdout.strip()

    def accept_current(self):
        self.success_worker()
        self.completed(self.enqueue('verify', key='v')['id'])
        self.completed(self.enqueue('review', key='r')['id'])
        return self.call('accept', 't1', '--owner', 'manager', '--note', 'evidence checked')

    def test_lifecycle_accept_requires_current_review_and_verify(self):
        self.success_worker()
        self.assertEqual(self.call('status', 't1')['state'], 'awaiting_acceptance')
        self.call('accept', 't1', '--owner', 'manager', '--note', 'reviewed', error='missing_evidence')
        verification = self.enqueue('verify', key='v')
        self.assertEqual(self.completed(verification['id'])['status'], 'succeeded')
        review = self.enqueue('review', key='r')
        self.assertEqual(self.completed(review['id'])['status'], 'succeeded')
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'claude', '--session', 'paseo-test')
        context = self.call('context', 't1', '--runtime', 'codex')
        self.assertEqual(context['owner'], 'manager')
        self.assertEqual(context['session'], 'paseo-test')
        accepted = self.call('accept', 't1', '--owner', 'manager', '--note', 'All evidence independently checked')
        self.assertEqual(accepted['state'], 'accepted')
        # The worktree reservation is held until the manager commits and finalizes.
        self.create('t2')
        self.enqueue(task='t2', error='worktree_reserved')
        sha = self.commit_repo()
        self.assertEqual(self.call('finalize', 't1', '--owner', 'manager', '--commit', sha,
                                   '--note', 'manager committed')['state'], 'done')
        self.assertEqual(self.enqueue(task='t2')['status'], 'queued')
        self.assertEqual(self.completed(self.call('status', 't2')['attempts'][0]['id'])['status'], 'succeeded')

    def test_concurrent_idempotency_and_reservation(self):
        self.create()
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: self.enqueue(), range(4)))
        self.assertEqual(len({a['id'] for a in results}), 1)
        self.enqueue('review', key='one', error='idempotency_conflict')
        self.create('t2')
        self.enqueue(task='t2', error='worktree_reserved')
        self.enqueue(owner='other', error='owner_mismatch')
        self.call('wait', results[0]['id'], '--timeout', '0', error='wait_timeout')
        self.assertEqual(self.call('status', 't1')['state'], 'running')

    def test_freeze_and_missing_receipt_recovery_backup(self):
        self.write_ticket(edit='partial\n', no_receipt=True)
        self.create()
        attempt = self.enqueue()
        self.write_ticket(edit='wrong\n')
        (self.skill / 'scripts/pi-openrouter-worker.sh').write_text('exit 42\n')
        self.runner()
        done = self.completed(attempt['id'])
        self.assertEqual(done['status'], 'failed')
        self.assertEqual((self.repo / 'source.txt').read_text(), 'partial\n')
        self.assertEqual(self.call('status', 't1')['state'], 'recovery_required')
        self.enqueue(key='retry', error='invalid_state')
        recovered = self.call('recover', 't1', '--owner', 'manager', '--note', 'Reviewed partial changes; inherit')
        self.assertEqual(recovered['state'], 'ready')
        bundle = Path(recovered['events'][-1]['body']['bundle'])
        self.assertTrue((bundle / 'SHA256SUMS').is_file())
        self.assertIn('partial', (bundle / 'tracked.patch').read_text())

    def test_block_handoff_atomic_idempotent_and_owner_changes(self):
        self.create()
        a = self.enqueue()
        self.call('cancel', a['id'], '--owner', 'manager', '--note', 'park')
        self.call('block', 't1', '--owner', 'manager', '--reason', 'dependency', '--resume-note', 'read upstream', '--wake-condition', 'upstream ready')
        self.enqueue(key='blocked', error='invalid_state')
        args = ('handoff', 't1', '--owner', 'manager', '--to', 'replacement', '--key', 'h1', '--note', 'Continue pending dependency')
        successor = self.call(*args)
        self.assertEqual(self.call(*args)['id'], successor['id'])
        self.assertEqual(successor['state'], 'blocked')
        self.assertEqual(successor['blocked']['reason'], 'dependency')
        self.assertEqual(self.call('status', 't1')['state'], 'handed_off')
        self.create('t2')
        self.enqueue(task='t2', error='worktree_reserved')
        self.call('unblock', successor['id'], '--owner', 'manager', '--note', 'resolved', error='owner_mismatch')
        self.call('unblock', successor['id'], '--owner', 'replacement', '--note', 'resolved')
        self.assertEqual(self.call(*args)['id'], successor['id'])
        self.assertEqual(self.enqueue(task=successor['id'], owner='replacement')['status'], 'queued')

    def test_runner_restart_adopts_live_work_without_relaunch(self):
        self.write_ticket(edit='edited\n', gate=str(self.base / 'gate'))
        self.create(); a = self.enqueue(); runner = self.runner()
        self.eventually(self.started.exists)
        runner.kill(); runner.wait()
        self.runner()
        self.call('recover', 't1', '--owner', 'manager', '--note', 'must not recover live', error='active_attempt')
        (self.base / 'gate').touch()
        self.assertEqual(self.completed(a['id'])['status'], 'succeeded')
        self.assertEqual(len(self.call('status', 't1')['attempts']), 1)

    def test_source_changes_after_enqueue_fail_closed(self):
        self.create(); a = self.enqueue()
        (self.repo / 'source.txt').write_text('external edit\n')
        self.runner()
        self.assertEqual(self.completed(a['id'])['status'], 'failed')
        self.assertFalse(self.started.exists())
        self.assertEqual(self.call('status', 't1')['state'], 'recovery_required')
        self.call('abandon', 't1', '--owner', 'manager', '--note', 'give up', error='recovery_required')

    def test_every_verified_command_must_pass_on_current_version(self):
        self.success_worker()
        flag = self.base / 'flag'  # outside the repo: flipping it does not change the fingerprint
        gated = f"import pathlib; assert pathlib.Path({str(flag)!r}).exists()"
        self.assertEqual(self.completed(self.enqueue('verify', key='a1', command=gated)['id'])['status'], 'failed')
        self.assertEqual(self.completed(self.enqueue('verify', key='b1')['id'])['status'], 'succeeded')
        self.completed(self.enqueue('review', key='r')['id'])
        # The later passing command must not hide the earlier failing one.
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='stale_evidence')
        flag.touch()
        self.assertEqual(self.completed(self.enqueue('verify', key='a2', command=gated)['id'])['status'], 'succeeded')
        accepted = self.call('accept', 't1', '--owner', 'manager', '--note', 'both commands pass')
        evidence = accepted['events'][-1]['body']['evidence']
        self.assertEqual(len(evidence['verify']), 2)

    def test_each_verified_command_must_be_rerun_after_source_changes(self):
        self.success_worker()
        other = "assert open('source.txt').read().endswith('\\n')"
        self.completed(self.enqueue('verify', key='a1', command=other)['id'])
        # A fix lands (a follow-up worker run); only command B is re-verified on the new version.
        self.write_ticket(edit='fixed\n')
        self.completed(self.enqueue(key='fix')['id'])
        self.completed(self.enqueue('verify', key='b1', command="assert open('source.txt').read() == 'fixed\\n'")['id'])
        self.completed(self.enqueue('review', key='r')['id'])
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='stale_evidence')
        self.completed(self.enqueue('verify', key='a2', command=other)['id'])
        self.assertEqual(self.call('accept', 't1', '--owner', 'manager', '--note', 'all rerun')['state'], 'accepted')

    def test_low_tier_review_waiver_only_before_any_review(self):
        self.success_worker()
        self.completed(self.enqueue('verify', key='v')['id'])
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='missing_evidence')
        self.call('accept', 't1', '--owner', 'manager', '--note', 'ok', '--review-waiver', ' ', error='missing_value')
        accepted = self.call('accept', 't1', '--owner', 'manager', '--note', 'ok', '--review-waiver', 'low tier: docs only')
        self.assertEqual(accepted['state'], 'accepted')
        self.assertEqual(accepted['events'][-1]['body']['evidence']['review'], {'waived': 'low tier: docs only'})
        # The accepted task still holds the worktree until the manager commits and finalizes.
        sha = self.commit_repo()
        self.assertEqual(self.call('finalize', 't1', '--owner', 'manager', '--commit', sha,
                                   '--note', 'committed')['state'], 'done')
        # Once a review ran, the task is high tier: waiving is refused even if review failed.
        self.create('t2')
        self.write_ticket(edit='again\n')
        self.completed(self.enqueue(task='t2', key='w2')['id'])
        self.completed(self.enqueue('verify', task='t2', key='v2',
                                    command="assert open('source.txt').read() == 'again\\n'")['id'])
        self.assertEqual(self.completed(self.enqueue('review', task='t2', key='r2', prompt='empty')['id'])['status'], 'failed')
        self.call('accept', 't2', '--owner', 'manager', '--note', 'ok', '--review-waiver', 'low', error='review_required')

    def test_review_canceled_before_running_does_not_block_waiver(self):
        self.success_worker()
        self.completed(self.enqueue('verify', key='v')['id'])
        self.runners[0].terminate(); self.runners[0].wait()
        queued = self.enqueue('review', key='mistake')
        self.call('cancel', queued['id'], '--owner', 'manager', '--note', 'low tier after all')
        self.assertEqual(self.call('accept', 't1', '--owner', 'manager', '--note', 'ok',
                                   '--review-waiver', 'low tier')['state'], 'accepted')

    def test_untracked_ticket_or_prompt_inside_worktree_rejected(self):
        inside = self.repo / '_tickets' / 'T1.md'
        inside.parent.mkdir()
        inside.write_text(self.ticket.read_text())
        self.call('create', '--workdir', self.repo, '--ticket', inside, '--owner', 'm', '--id', 'in', error='inside_worktree')
        (self.repo / '.gitignore').write_text('_tickets/\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.gitignore'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'ignore tickets'], check=True)
        self.call('create', '--workdir', self.repo, '--ticket', inside, '--owner', 'm', '--id', 'in')
        prompt = self.repo / 'review-prompt.md'
        prompt.write_text('review')
        self.call('review', 'in', '--owner', 'm', '--key', 'r', '--skill', self.skill, '--prompt', prompt,
                  error='inside_worktree')

    def test_abandon_releases_worktree_without_touching_source(self):
        self.write_ticket(edit='edited\n')
        self.create()
        a = self.enqueue()
        self.call('abandon', 't1', '--owner', 'manager', '--note', 'stop', error='active_attempt')
        self.call('cancel', a['id'], '--owner', 'manager', '--note', 'park')
        # Leave half-finished work in the tree: a worker writes, then the manager gives up.
        self.runner()
        self.completed(self.enqueue(key='partial')['id'])
        self.assertEqual((self.repo / 'source.txt').read_text(), 'edited\n')
        self.create('t2')
        self.enqueue(task='t2', error='worktree_reserved')
        self.call('abandon', 't1', '--owner', 'other', '--note', 'stop', error='owner_mismatch')
        abandoned = self.call('abandon', 't1', '--owner', 'manager', '--note', 'superseded by t2')
        self.assertEqual(abandoned['state'], 'abandoned')
        self.assertEqual(self.call('context', 't1', '--runtime', 'claude')['next_step'][:6], 'Closed')
        self.enqueue(key='again', error='closed_task')
        # Abandon neither resets nor cleans: the half-finished edit stays for the manager to handle.
        self.assertEqual((self.repo / 'source.txt').read_text(), 'edited\n')
        self.assertEqual(subprocess.run(['git', '-C', str(self.repo), 'status', '--porcelain'],
                                        capture_output=True, text=True).stdout, ' M source.txt\n')
        self.assertEqual(self.enqueue(task='t2')['status'], 'queued')

    def test_stale_or_tampered_proof_cannot_accept(self):
        self.success_worker()
        v = self.enqueue('verify', key='v'); self.completed(v['id'])
        r = self.enqueue('review', key='r'); self.completed(r['id'])
        (self.repo / 'source.txt').write_text('post-review edit\n')
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='stale_evidence')
        (self.repo / 'source.txt').write_text('edited\n')
        (Path(r['directory']) / 'stdout.log').write_text('replaced report')
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='changed_evidence')
        import hashlib
        result_path = Path(r['directory']) / 'result.json'
        result = json.loads(result_path.read_text())
        result['proof']['sha256'] = hashlib.sha256(b'replaced report').hexdigest()
        result_path.write_text(json.dumps(result))
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='changed_evidence')

    def test_empty_review_and_failed_verification_not_accepted(self):
        self.success_worker()
        r = self.enqueue('review', key='empty', prompt='empty')
        self.assertEqual(self.completed(r['id'])['status'], 'failed')
        v = self.enqueue('verify', key='fail', command='raise SystemExit(7)')
        self.assertEqual(self.completed(v['id'])['status'], 'failed')
        self.call('accept', 't1', '--owner', 'manager', '--note', 'no', error='stale_evidence')

    def test_mutating_review_requires_recovery(self):
        self.success_worker()
        r = self.enqueue('review', key='mutate', prompt='mutate')
        self.assertEqual(self.completed(r['id'])['status'], 'failed')
        self.assertEqual(self.call('status', 't1')['state'], 'recovery_required')

    def test_state_cannot_live_inside_source(self):
        self.state = self.repo / 'state'
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'm', error='state_inside_worktree')

    def test_uncertain_launch_requires_recovery_without_execution(self):
        import sqlite3
        self.create(); a = self.enqueue()
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            db.execute("UPDATE attempts SET status='launching' WHERE id=?", (a['id'],))
        self.runner()
        self.assertEqual(self.completed(a['id'])['status'], 'interrupted')
        self.assertFalse(self.started.exists())
        self.assertEqual(self.call('status', 't1')['state'], 'recovery_required')

    def test_dead_supervisor_with_live_descendant_stays_active(self):
        self.write_ticket(edit='partial\n', gate=str(self.base / 'gate'))
        self.create(); a = self.enqueue(); self.runner()
        self.eventually(self.started.exists)
        process = self.call('status', 't1')['attempts'][0]['process']
        os.kill(process['pid'], signal.SIGKILL)
        time.sleep(.5)
        self.call('wait', a['id'], '--timeout', '0', error='wait_timeout')
        self.call('recover', 't1', '--owner', 'manager', '--note', 'not yet', error='active_attempt')
        (self.base / 'gate').touch()
        self.assertEqual(self.completed(a['id'])['status'], 'interrupted')
        self.assertEqual(self.call('recover', 't1', '--owner', 'manager', '--note', 'inherit')['state'], 'ready')

    def test_os_lock_blocks_other_state_and_recovery(self):
        import fcntl
        self.write_ticket(no_receipt=True)
        self.create(); a = self.enqueue(); self.runner(); self.completed(a['id'])
        with open(self.repo / '.git/osrelay.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.call('recover', 't1', '--owner', 'manager', '--note', 'blocked', error='busy')
        self.call('recover', 't1', '--owner', 'manager', '--note', 'inherit')

    def test_pid_reuse_does_not_adopt_unrelated_process(self):
        import sqlite3
        self.create(); a = self.enqueue()
        record = {'pid': os.getpid(), 'starttime': '0', 'boot_id': 'wrong-boot'}
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            db.execute("UPDATE attempts SET status='running',process=? WHERE id=?", (json.dumps(record), a['id']))
        self.runner()
        self.assertEqual(self.completed(a['id'])['status'], 'interrupted')
        self.assertEqual(self.call('recover', 't1', '--owner', 'manager', '--note', 'inherit')['state'], 'ready')

    def test_two_runners_cannot_dispatch_twice(self):
        self.create()
        first = self.runner()
        self.eventually(lambda: (self.state / 'runner.json').exists())
        second = self.runner()
        self.assertNotEqual(second.wait(timeout=5), 0)
        a = self.enqueue()
        self.assertEqual(self.completed(a['id'])['status'], 'succeeded')
        self.assertIsNone(first.poll())
        self.assertEqual(sum(e['kind'] == 'started' for e in self.call('status', 't1')['events']), 1)

    def test_slow_recovery_does_not_lock_other_tasks(self):
        import shlex
        self.write_ticket(no_receipt=True)
        self.create(); a = self.enqueue(); self.runner(); self.completed(a['id'])
        script = Path(a['directory']) / 'skill/scripts/backup-worktree.sh'
        original = script.read_text()
        started = self.base / 'backup-started'
        release = self.base / 'backup-release'
        script.write_text('touch ' + shlex.quote(str(started)) + '\nwhile [ ! -f '
                          + shlex.quote(str(release)) + ' ]; do sleep .05; done\n' + original)
        recovery = subprocess.Popen([*CLI, '--state', str(self.state), 'recover', 't1',
                                     '--owner', 'manager', '--note', 'inherit'], cwd=ROOT,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.eventually(started.exists)
            other = subprocess.run([*CLI, '--state', str(self.state), 'create', '--id', 'independent',
                                    '--workdir', str(self.repo), '--ticket', str(self.ticket), '--owner', 'other'],
                                   cwd=ROOT, capture_output=True, text=True, timeout=2)
            self.assertEqual(other.returncode, 0, other.stderr)
        finally:
            release.touch()
            stdout, stderr = recovery.communicate(timeout=8)
            self.assertEqual(recovery.returncode, 0, stderr)

    def test_glm_route_preserves_custom_cli_path(self):
        custom = self.base / 'custom zcode'
        custom.write_text('#!/bin/sh\nprintf "custom-zcode-ok\\n"\n')
        custom.chmod(0o700)
        helper = self.skill / 'scripts/zcode-cloud-worker.sh'
        helper.write_text('# ZCODE_MODEL=fixture-glm\n"$ZCODE_CLI_BIN" || exit 9\n'
                          'exec bash "$(dirname "$0")/pi-openrouter-worker.sh" "$@"\n')
        self.write_ticket(edit='edited\n'); self.create()
        self.env['ZCODE_CLI_BIN'] = str(custom)
        a = self.enqueue(engine='glm')
        self.runner()
        self.assertEqual(self.completed(a['id'])['status'], 'succeeded')
        self.assertEqual(a['route']['model'], 'fixture-glm')
        self.assertIn('custom-zcode-ok', (Path(a['directory']) / 'stdout.log').read_text())
        self.assertEqual((self.repo / 'source.txt').read_text(), 'edited\n')

    def test_sigterm_drains_worker_and_collects_result(self):
        self.write_ticket(gate=str(self.base / 'gate'))
        self.create(); a = self.enqueue(); runner = self.runner()
        self.eventually(self.started.exists)
        runner.terminate()
        time.sleep(.3)
        self.assertIsNone(runner.poll())
        (self.base / 'gate').touch()
        self.assertEqual(runner.wait(timeout=8), 0)
        self.assertEqual(self.completed(a['id'])['status'], 'succeeded')
        self.assertEqual(self.call('status', 't1')['state'], 'awaiting_acceptance')

    def test_backup_failure_keeps_recovery_required(self):
        self.write_ticket(no_receipt=True)
        self.create(); a = self.enqueue(); self.runner(); self.completed(a['id'])
        script = Path(a['directory']) / 'skill/scripts/backup-worktree.sh'
        script.write_text('exit 9\n')
        self.call('recover', 't1', '--owner', 'manager', '--note', 'inherit', error='backup_failed')
        self.assertEqual(self.call('status', 't1')['state'], 'recovery_required')

    def session_file(self, key, workdir):
        import hashlib
        digest = hashlib.sha256(workdir.encode()).hexdigest()[:12]
        return self.home / '.local/state/osslab-manager/pi-sessions' / f'{key}-{digest}' / f'fixture_{key}.jsonl'

    def git_repo(self, path):
        path.mkdir()
        for args in [('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid')]:
            subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)
        (path / 'source.txt').write_text('initial\n')
        subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(path), 'commit', '-qm', 'fixture'], check=True)
        return path

    def test_goal_context_lists_child_receipts_and_evidence(self):
        note = 'ship the chains'
        self.assertEqual(self.call('goal', 'create', '--id', 'goal-1', '--owner', 'spec', '--note', note)['note'], note)
        self.assertEqual(self.call('goal', 'create', '--id', 'goal-1', '--owner', 'spec', '--note', note)['id'], 'goal-1')
        self.call('goal', 'create', '--id', 'goal-1', '--owner', 'spec', '--note', 'different', error='id_conflict')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'spec', '--id', 'goal-1',
                  error='id_conflict')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'spec', '--id', 't1',
                  '--goal', 'goal-1', error='missing_value')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'spec', '--id', 't1',
                  '--goal', 'missing', '--chain', 'chain-a', error='not_found')
        self.write_ticket(edit='edited\n')
        first = self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'spec', '--id', 't1',
                          '--goal', 'goal-1', '--chain', 'chain-a')
        self.assertEqual(first['chain'], 'chain-a')
        other = self.git_repo(self.base / 'repo-b')
        second = self.call('create', '--workdir', other, '--ticket', self.ticket, '--owner', 'spec', '--id', 't2',
                           '--goal', 'goal-1', '--chain', 'chain-b')
        self.assertNotEqual(first['workdir'], second['workdir'])
        attempt = self.enqueue(owner='spec')
        self.runner()
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        self.completed(self.enqueue('verify', key='v', owner='spec')['id'])
        later = self.completed(self.enqueue('verify', key='v2', owner='spec')['id'])
        other = self.completed(self.enqueue('verify', key='v-other', owner='spec',
                                            command="assert open('source.txt').read().endswith('\\n')")['id'])
        review = self.completed(self.enqueue('review', key='r', owner='spec')['id'])
        self.runners[0].terminate(); self.runners[0].wait()
        canceled = self.enqueue('review', key='r-cancel', owner='spec')
        self.call('cancel', canceled['id'], '--owner', 'spec', '--note', 'queued by mistake')
        view = self.call('context', 'goal-1', '--runtime', 'codex')
        self.assertEqual(view['kind'], 'goal')
        self.assertEqual([child['id'] for child in view['children']], ['t1', 't2'])
        done, pending = view['children']
        self.assertEqual(done['chain'], 'chain-a')
        self.assertTrue(done['receipt']['sha256'])
        self.assertEqual(done['review']['status'], 'succeeded')
        self.assertTrue(done['review']['sha256'])
        self.assertEqual(len(done['verify']), 2)
        by_command = {json.dumps(item['command']): item for item in done['verify']}
        self.assertEqual(by_command[json.dumps(later['request']['command'])]['attempt'], later['id'])
        self.assertEqual(by_command[json.dumps(other['request']['command'])]['attempt'], other['id'])
        self.assertEqual(done['review']['attempt'], review['id'])
        self.assertIsNone(pending['receipt'])
        self.assertEqual(pending['state'], 'ready')
        listed = self.call('list')
        self.assertEqual({row['id']: row['goal_id'] for row in listed}, {'t1': 'goal-1', 't2': 'goal-1'})
        successor = self.call('handoff', 't2', '--owner', 'spec', '--to', 'build', '--key', 'h', '--note', 'build it')
        self.assertEqual(successor['goal_id'], 'goal-1')
        self.assertEqual(successor['chain'], 'chain-b')
        self.assertEqual([child['id'] for child in self.call('context', 'goal-1', '--runtime', 'claude')['children']],
                         ['t1', 't2', successor['id']])

    def test_resume_continues_this_tasks_session_and_stops_at_two(self):
        self.write_ticket(edit='edited\n')
        original = self.ticket.read_text()
        created = self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager',
                            '--id', 't1', '--chain', 'shared-chain')
        fresh = self.enqueue()
        self.runner()
        self.assertEqual(self.completed(fresh['id'])['status'], 'succeeded')
        self.assertFalse(fresh['request']['resume'])
        # A fresh pi run opens a session named after its own attempt, not the chain.
        self.assertEqual(fresh['request']['session'], fresh['id'])
        self.assertIn('從零開始', (Path(fresh['directory']) / 'ticket.md').read_text())
        session = self.session_file(fresh['id'], created['workdir'])
        self.assertTrue(session.is_file())
        session.unlink()
        self.enqueue(key='no-session', resume=True, error='resume_refused')
        session.touch()
        self.ticket.write_text(original + 'changed\n')
        self.enqueue(key='ticket-changed', resume=True, error='resume_refused')
        self.ticket.write_text(original)
        receipt = Path(fresh['directory']) / 'receipt.md'
        receipt.write_text('## 4. 風險與存疑\n契約沒寫清楚\n')
        self.enqueue(key='doubt', resume=True, error='resume_refused')
        receipt.unlink()
        self.enqueue(key='missing-receipt', resume=True, error='resume_refused')
        receipt.write_text('## 4. 風險與存疑\n   \n')
        (self.repo / 'marker.txt').write_text('x\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'marker.txt'], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'move head'], check=True)
        self.enqueue(key='head', resume=True, error='resume_refused')
        subprocess.run(['git', '-C', str(self.repo), 'reset', '-q', '--hard', 'HEAD~1'], check=True)
        self.enqueue(engine='glm', key='glm', resume=True, error='resume_refused')
        from osrelay.runner import command_for
        for key in ('resume-1', 'resume-2'):
            attempt = self.enqueue(key=key, resume=True)
            self.assertTrue(attempt['request']['resume'])
            self.assertEqual(attempt['request']['session'], fresh['id'])
            self.assertIn(f"接續本單 pi session {fresh['id']}", (Path(attempt['directory']) / 'ticket.md').read_text())
            argv = command_for(attempt, {'workdir': created['workdir'], 'chain': 'shared-chain'})
            self.assertEqual(argv[argv.index('--resume') + 1:argv.index('--resume') + 3], [fresh['id'], '--require-resume'])
            self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        self.enqueue(key='resume-3', resume=True, error='resume_refused')
        # Replaying an accepted resume key still returns that attempt.
        self.assertEqual(self.enqueue(key='resume-2', resume=True)['status'], 'succeeded')
        # A later fresh run opens a new session; resume then follows the newest one.
        again = self.enqueue(key='fresh-2')
        self.assertEqual(self.completed(again['id'])['status'], 'succeeded')
        self.assertEqual(self.enqueue(key='resume-new', resume=True)['request']['session'], again['id'])

    def test_helper_refusal_fails_attempt_without_recovery_or_using_the_limit(self):
        self.write_ticket(edit='edited\n')
        created = self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager', '--id', 't1')
        runner = self.runner()
        fresh = self.enqueue()
        self.assertEqual(self.completed(fresh['id'])['status'], 'succeeded')
        runner.terminate(); runner.wait()
        # Relay's gate passes at enqueue; the session disappears before the helper runs.
        queued = self.enqueue(key='r1', resume=True)
        session = self.session_file(fresh['id'], created['workdir'])
        session.unlink()
        self.runner()
        done = self.completed(queued['id'])
        self.assertEqual(done['status'], 'failed')
        self.assertEqual(json.loads(done['error'])['code'], 'resume_refused')
        self.assertEqual(self.call('status', 't1')['state'], 'awaiting_acceptance')
        # No recovery happened, and the refused try does not count toward the limit of two.
        session.touch()
        for key in ('r2', 'r3'):
            self.assertEqual(self.completed(self.enqueue(key=key, resume=True)['id'])['status'], 'succeeded')
        self.enqueue(key='r4', resume=True, error='resume_refused')

    def test_resume_is_per_task_even_on_a_shared_chain(self):
        self.write_ticket(edit='edited\n')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager',
                  '--id', 't1', '--chain', 'shared-chain')
        self.runner()
        first = self.enqueue()
        self.assertEqual(self.completed(first['id'])['status'], 'succeeded')
        self.call('abandon', 't1', '--owner', 'manager', '--note', 'next ticket on the same chain')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager',
                  '--id', 't2', '--chain', 'shared-chain')
        # t1's session exists, but t2 has no worker of its own yet: nothing to continue.
        self.enqueue(task='t2', key='r0', resume=True, error='resume_refused')
        second = self.enqueue(task='t2', key='w')
        self.assertEqual(self.completed(second['id'])['status'], 'succeeded')
        resumed = self.enqueue(task='t2', key='r1', resume=True)
        self.assertEqual(resumed['request']['session'], second['id'])

    def test_resume_refused_after_recovery(self):
        self.write_ticket(edit='edited\n')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager', '--id', 't1')
        self.runner()
        self.assertEqual(self.completed(self.enqueue()['id'])['status'], 'succeeded')
        self.write_ticket(edit='partial\n', no_receipt=True)
        self.assertEqual(self.completed(self.enqueue(key='broken')['id'])['status'], 'failed')
        self.call('recover', 't1', '--owner', 'manager', '--note', 'inherit partial')
        self.write_ticket(edit='edited\n')
        # A succeeded worker and its session exist, but recovered work always starts fresh.
        self.enqueue(key='again', resume=True, error='resume_refused')

    def test_resume_needs_a_succeeded_worker(self):
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager',
                  '--id', 't1', '--chain', 'c')
        self.enqueue(resume=True, error='resume_refused')

    def test_canceled_resume_does_not_consume_the_limit(self):
        self.write_ticket(edit='edited\n')
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager',
                  '--id', 't1', '--chain', 'relaytest-cancel')
        runner = self.runner()
        self.assertEqual(self.completed(self.enqueue()['id'])['status'], 'succeeded')
        runner.terminate(); runner.wait()
        for key in ('skip-1', 'skip-2'):
            queued = self.enqueue(key=key, resume=True)
            self.assertEqual(queued['status'], 'queued')
            self.call('cancel', queued['id'], '--owner', 'manager', '--note', 'do not count')
        self.runner()
        kept = self.enqueue(key='kept', resume=True)
        self.assertEqual(self.completed(kept['id'])['status'], 'succeeded')

    def test_real_pi_helper_opens_then_continues_the_session(self):
        # The real osslab-manager helper (snapshot) with a fake pi: no plant, no model call.
        shutil.copytree(ROOT / 'tests/fixtures/real-pi', self.skill, dirs_exist_ok=True)
        secrets = self.home / '.openclaw/secrets'
        secrets.mkdir(parents=True)
        (secrets / 'openrouter.env').write_text('OPENROUTER_API_KEY=fake-key\n')
        fake = self.base / 'bin'
        fake.mkdir()
        (fake / 'pi').write_text(f"""#!{sys.executable}
import json, os, pathlib, re, sys
args = sys.argv[1:]
with open(os.environ['HOME'] + '/pi-argv.jsonl', 'a') as log:
    log.write(json.dumps(args) + '\\n')
if '--session-dir' in args:
    d = pathlib.Path(args[args.index('--session-dir') + 1])
    (d / ('2026_' + args[args.index('--session-id') + 1] + '.jsonl')).write_text('{{}}\\n')
ticket = re.search(r'工單：(\\S+?\\.md)', args[-1])[1]
receipt = re.search(r'本輪回執唯一指定路徑：([^\\n]+)', pathlib.Path(ticket).read_text())[1]
pathlib.Path('source.txt').write_text('edited\\n')
pathlib.Path(receipt).write_text('# 回執\\n## 4. 風險與存疑\\n無\\n')
""")
        (fake / 'pi').chmod(0o700)
        self.env['PATH'] = f"{fake}:{self.env['PATH']}"
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager', '--id', 't1')
        self.runner()
        fresh = self.enqueue()
        self.assertEqual(self.completed(fresh['id'])['status'], 'succeeded')
        resumed = self.enqueue(key='resume', resume=True)
        self.assertEqual(self.completed(resumed['id'])['status'], 'succeeded')
        calls = [json.loads(line) for line in (self.home / 'pi-argv.jsonl').read_text().splitlines()]
        self.assertEqual([c[c.index('--session-id') + 1] for c in calls], [fresh['id'], fresh['id']])
        self.assertNotIn('記憶不是證據', calls[0][-1])
        self.assertIn('記憶不是證據', calls[1][-1])
        self.assertIn('session=resumed(1/2', (Path(resumed['directory']) / 'stderr.log').read_text())

    def test_v1_database_upgrades_without_dropping_tasks(self):
        import sqlite3
        self.state.mkdir()
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            db.executescript('''
              CREATE TABLE tasks (
                id TEXT PRIMARY KEY, workdir TEXT NOT NULL, ticket TEXT NOT NULL,
                owner TEXT NOT NULL, state TEXT NOT NULL, parent TEXT,
                runtime TEXT, session TEXT, blocked TEXT, note TEXT,
                created TEXT NOT NULL, updated TEXT NOT NULL);
              CREATE TABLE reservations (
                workdir TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL);
              CREATE TABLE attempts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                kind TEXT NOT NULL, request_key TEXT NOT NULL, request TEXT NOT NULL,
                status TEXT NOT NULL, directory TEXT NOT NULL, route TEXT NOT NULL,
                before_state TEXT NOT NULL, after_state TEXT, process TEXT,
                exit_code INTEGER, error TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
                UNIQUE(task_id, request_key));
              CREATE TABLE events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, attempt_id TEXT,
                kind TEXT NOT NULL, body TEXT NOT NULL, at TEXT NOT NULL);
              PRAGMA user_version=1;
            ''')
            db.execute("INSERT INTO tasks(id,workdir,ticket,owner,state,created,updated) VALUES(?,?,?,?,?,?,?)",
                       ('old', '/tmp/not-a-repo', str(self.ticket), 'manager', 'ready', 't', 't'))
            legacy = {"kind": "worker", "engine": "pi", "skill": str(self.skill.resolve()),
                      "prompt": None, "command": None, "note": None}
            db.execute("INSERT INTO attempts(id,task_id,kind,request_key,request,status,directory,route,before_state,created,updated) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ('attempt-old', 'old', 'worker', 'one', json.dumps(legacy), 'succeeded', '/tmp/attempt-old',
                        '{}', '{"head":"abc"}', 't', 't'))
        listed = self.call('list')
        self.assertEqual(listed[0]['id'], 'old')
        self.assertIsNone(listed[0]['goal_id'])
        self.assertIsNone(listed[0]['chain'])
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            columns = {row[1] for row in db.execute('PRAGMA table_info(tasks)')}
        self.assertIn('goal_id', columns)
        self.assertIn('chain', columns)
        self.assertEqual(self.enqueue(task='old', key='one')['id'], 'attempt-old')

    def test_accepted_task_refuses_new_work_handoff_and_block(self):
        accepted = self.accept_current()
        self.assertEqual(accepted['state'], 'accepted')
        self.enqueue(key='again', error='invalid_state')
        self.call('block', 't1', '--owner', 'manager', '--reason', 'r', '--resume-note', 'n',
                  '--wake-condition', 'w', error='invalid_state')
        self.call('handoff', 't1', '--owner', 'manager', '--to', 'other', '--key', 'h', '--note', 'n',
                  error='invalid_state')
        self.assertEqual(self.call('status', 't1')['state'], 'accepted')
        self.create('t2')
        self.enqueue(task='t2', error='worktree_reserved')
        # abandon is the explicit exit and releases the worktree.
        self.call('abandon', 't1', '--owner', 'manager', '--note', 'superseded')
        self.assertEqual(self.enqueue(task='t2')['status'], 'queued')

    def test_finalize_allows_no_change_acceptance_at_base(self):
        self.write_ticket()
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        self.completed(self.enqueue('verify', key='v',
                                    command="assert open('source.txt').read() == 'initial\\n'")['id'])
        self.completed(self.enqueue('review', key='r')['id'])
        accepted = self.call('accept', 't1', '--owner', 'manager', '--note', 'no source change')
        recorded = accepted['events'][-1]['body']
        self.assertEqual(recorded['tree'], recorded['base_tree'])
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'claude', '--session', 'paseo-finalize')
        done = self.call('finalize', 't1', '--owner', 'manager', '--commit', recorded['base'],
                         '--note', 'close at original HEAD')
        self.assertEqual(done['state'], 'done')
        self.assertEqual(done['events'][-1]['body']['commit'], recorded['base'])

    def test_finalize_is_idempotent_and_refuses_other_commit(self):
        self.accept_current()
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'claude', '--session', 'paseo-other')
        sha = self.commit_repo()
        first = self.call('finalize', 't1', '--owner', 'manager', '--commit', sha, '--note', 'commit')
        self.assertEqual(first['state'], 'done')
        again = self.call('finalize', 't1', '--owner', 'manager', '--commit', sha, '--note', 'commit')
        self.assertEqual(again['state'], 'done')
        self.assertEqual(sum(1 for event in again['events'] if event['kind'] == 'finalized'), 1)
        base = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD~1'], check=True,
                              capture_output=True, text=True).stdout.strip()
        self.call('finalize', 't1', '--owner', 'manager', '--commit', base, '--note', 'x',
                  error='commit_mismatch')

    def test_finalize_never_fabricates_proof_for_legacy_done(self):
        import sqlite3
        self.create()
        head = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], check=True,
                              capture_output=True, text=True).stdout.strip()
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            db.execute("UPDATE tasks SET state='done' WHERE id='t1'")
        self.call('finalize', 't1', '--owner', 'manager', '--commit', head, '--note', 'x',
                  error='invalid_state')
        self.assertEqual([e for e in self.call('status', 't1')['events'] if e['kind'] == 'finalized'], [])
        self.assertEqual(self.call('context', 't1', '--runtime', 'codex')['state'], 'done')

    def test_finalize_refusals_keep_accepted_lock(self):
        accepted = self.accept_current()
        base = accepted['events'][-1]['body']['base']
        self.create('t2')
        self.call('finalize', 't1', '--owner', 'other', '--commit', base, '--note', 'x',
                  error='owner_mismatch')
        good = self.commit_repo('accepted tree')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', 'f' * 40, '--note', 'x',
                  error='unknown_commit')
        (self.repo / 'scratch.txt').write_text('x\n')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', good, '--note', 'x',
                  error='dirty_worktree')
        (self.repo / 'scratch.txt').unlink()
        (self.repo / 'source.txt').write_text('other\n')
        other = self.commit_repo('other')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', other, '--note', 'x',
                  error='tree_mismatch')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', good, '--note', 'x',
                  error='head_mismatch')
        self.assertEqual(self.call('status', 't1')['state'], 'accepted')
        self.enqueue(task='t2', error='worktree_reserved')

    def test_finalize_requires_direct_child_and_matching_tree(self):
        accepted = self.accept_current()
        base = accepted['events'][-1]['body']['base']
        (self.repo / 'source.txt').write_text('diverged\n')
        diverged = self.commit_repo('diverged')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', diverged, '--note', 'x',
                  error='tree_mismatch')
        subprocess.run(['git', '-C', str(self.repo), 'reset', '--hard', base], check=True, capture_output=True)
        (self.repo / 'source.txt').write_text('edited\n')
        good = self.commit_repo('good')
        subprocess.run(['git', '-C', str(self.repo), 'commit', '--allow-empty', '-qm', 'extra'],
                       check=True, capture_output=True)
        extra = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], check=True,
                               capture_output=True, text=True).stdout.strip()
        self.call('finalize', 't1', '--owner', 'manager', '--commit', extra, '--note', 'x',
                  error='history_mismatch')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', good, '--note', 'x',
                  error='head_mismatch')
        subprocess.run(['git', '-C', str(self.repo), 'reset', '--hard', good], check=True, capture_output=True)
        self.assertEqual(self.call('finalize', 't1', '--owner', 'manager', '--commit', good,
                                   '--note', 'single child')['state'], 'done')

    def test_finalize_rejects_index_worktree_offset(self):
        accepted = self.accept_current()
        good = self.commit_repo('accepted tree')
        self.create('t2')
        self.enqueue(task='t2', error='worktree_reserved')
        # MM: stage an edit, then restore only the worktree. git diff HEAD (worktree
        # vs HEAD) is empty, but the index still differs from HEAD.
        (self.repo / 'source.txt').write_text('staged then reverted\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'source.txt'], check=True, capture_output=True)
        (self.repo / 'source.txt').write_text('edited\n')  # restore worktree only; index keeps the staged edit
        self.assertEqual(subprocess.run(['git', '-C', str(self.repo), 'status', '--porcelain'],
                                        capture_output=True, text=True).stdout, 'MM source.txt\n')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', good, '--note', 'x', error='dirty_worktree')
        self.assertEqual(self.call('status', 't1')['state'], 'accepted')
        self.enqueue(task='t2', error='worktree_reserved')
        subprocess.run(['git', '-C', str(self.repo), 'reset', '-q', 'HEAD', '--', 'source.txt'],
                       check=True, capture_output=True)
        # AD: stage a new file, then remove it from the worktree. git diff HEAD is
        # empty and the untracked list does not see it, but the index holds it.
        (self.repo / 'staged.txt').write_text('new\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'staged.txt'], check=True, capture_output=True)
        os.remove(self.repo / 'staged.txt')
        self.assertEqual(subprocess.run(['git', '-C', str(self.repo), 'status', '--porcelain'],
                                        capture_output=True, text=True).stdout, 'AD staged.txt\n')
        self.call('finalize', 't1', '--owner', 'manager', '--commit', good, '--note', 'x', error='dirty_worktree')
        self.assertEqual(self.call('status', 't1')['state'], 'accepted')
        self.enqueue(task='t2', error='worktree_reserved')
        subprocess.run(['git', '-C', str(self.repo), 'reset', '-q', 'HEAD', '--', 'staged.txt'],
                       check=True, capture_output=True)
        # Once the index is clean the original commit finalizes.
        self.assertEqual(self.call('finalize', 't1', '--owner', 'manager', '--commit', good,
                                   '--note', 'committed')['state'], 'done')

    def test_finalize_covers_added_deleted_mode_and_symlink(self):
        (self.repo / 'keep.txt').write_text('keep\n')
        (self.repo / 'gone.txt').write_text('gone\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '-A'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-qm', 'base files'], check=True, capture_output=True)
        self.write_ticket(edit='edited\n')
        self.create()
        (self.repo / 'new.txt').write_text('new\n')
        (self.repo / 'gone.txt').unlink()
        (self.repo / 'keep.txt').chmod(0o755)
        os.symlink('keep.txt', self.repo / 'link.txt')
        attempt = self.enqueue()
        self.runner()
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        self.completed(self.enqueue('verify', key='v')['id'])
        self.completed(self.enqueue('review', key='r')['id'])
        accepted = self.call('accept', 't1', '--owner', 'manager', '--note', 'all kinds')
        sha = self.commit_repo('accepted content')
        committed_tree = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD^{tree}'], check=True,
                                        capture_output=True, text=True).stdout.strip()
        self.assertEqual(committed_tree, accepted['events'][-1]['body']['tree'])
        self.assertEqual(self.call('finalize', 't1', '--owner', 'manager', '--commit', sha,
                                   '--note', 'tree matches')['state'], 'done')


if __name__ == '__main__':
    unittest.main()
