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
sys.path.insert(0, str(ROOT))
from osrelay import wake  # noqa: E402  (v1.4 waker runs in-process with an injected clock)
from osrelay.artifacts import now  # noqa: E402
from osrelay.store import Store  # noqa: E402


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
        # Never reach the real Paseo daemon from tests; wake tests point this at a fake helper.
        self.env = dict(os.environ, HOME=str(self.home), OSRELAY_WAKE_HELPER='off')

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
        if kind in ('run', 'review') and kwargs.get('engine'):
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

    def test_glm_review_is_explicit_frozen_and_distinct_from_glm_worker(self):
        self.success_worker()
        self.completed(self.enqueue('verify', key='v')['id'])
        default = self.enqueue('review', key='default')
        self.assertEqual(default['route']['engine'], 'codex')
        self.completed(default['id'])
        review = self.enqueue('review', key='glm', engine='glm')
        self.assertEqual(review['route']['engine'], 'glm')
        self.assertEqual(review['route']['model'], 'GLM-5.3')
        self.assertEqual(review['route']['effort'], 'max')
        self.assertEqual(review['route']['helper'], 'zcode-readonly-review.sh')
        # A changed engine is a changed request, even under the same key.
        self.enqueue('review', key='glm', error='idempotency_conflict')
        self.assertEqual(self.completed(review['id'])['status'], 'succeeded')
        self.assertEqual(self.call('accept', 't1', '--owner', 'manager', '--note', 'GLM checked')['state'], 'accepted')
        from osrelay.artifacts import route
        self.assertEqual(route(self.skill, 'glm')['helper'], 'zcode-cloud-worker.sh')

    def test_codex_review_is_explicit_frozen_and_review_only(self):
        self.success_worker()
        self.completed(self.enqueue('verify', key='v')['id'])
        review = self.enqueue('review', key='codex', engine='codex')
        self.assertEqual(review['route'], {**review['route'], 'engine': 'codex', 'model': 'fixture/codex',
                                           'effort': 'medium', 'kind': 'review',
                                           'helper': 'codex-readonly-review.sh'})
        # A changed engine is a changed request, even under the same key.
        self.enqueue('review', key='codex', engine='glm', error='idempotency_conflict')
        self.assertEqual(self.completed(review['id'])['status'], 'succeeded')
        # Grok stays available by hand after codex and glm.
        grok = self.enqueue('review', key='grok', engine='grok')
        self.assertEqual((grok['route']['engine'], grok['route']['model']), ('grok', 'fixture/grok'))
        self.assertEqual(self.completed(grok['id'])['status'], 'succeeded')
        from osrelay.artifacts import RelayError, route
        self.assertEqual(route(self.skill, 'codex')['kind'], 'review')
        # Codex only reviews here; Codex as manager is a task runtime, not a worker engine.
        with self.assertRaises(RelayError):
            route(self.skill, 'codex', 'worker')
        with self.assertRaises(RelayError):
            route(self.skill, 'grok', 'worker')
        # The review effort is part of the frozen route; a helper that hides it is refused, not defaulted.
        helper = self.skill / 'scripts/codex-readonly-review.sh'
        helper.write_text(helper.read_text().replace(' -c model_reasoning_effort=medium', ''))
        with self.assertRaises(RelayError) as refused:
            route(self.skill, 'codex')
        self.assertEqual(refused.exception.code, 'unknown_route')

    def test_doctor_lists_optional_reviews_without_breaking_older_skills(self):
        installed = self.home / '.agents/skills/osslab-manager'
        installed.parent.mkdir(parents=True)
        installed.symlink_to(self.skill, target_is_directory=True)
        routes = self.call('doctor')['routes']
        self.assertEqual([r['helper'] for r in routes[3:]], ['codex-readonly-review.sh', 'zcode-readonly-review.sh'])
        self.assertEqual({r['kind'] for r in routes[3:]}, {'review'})
        (self.skill / 'scripts/codex-readonly-review.sh').unlink()
        self.assertEqual(len(self.call('doctor')['routes']), 4)
        (self.skill / 'scripts/zcode-readonly-review.sh').unlink()
        self.assertEqual(len(self.call('doctor')['routes']), 3)

    def test_new_file_intent_to_add_before_verification_remains_current(self):
        self.success_worker()
        (self.repo / 'new.txt').write_text('approved new file\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '-N', '--', 'new.txt'], check=True)
        self.completed(self.enqueue('verify', key='v')['id'])
        self.completed(self.enqueue('review', key='r')['id'])
        self.assertEqual(self.call('accept', 't1', '--owner', 'manager', '--note', 'New file verified')['state'], 'accepted')
        sha = self.commit_repo()
        self.assertEqual(self.call('finalize', 't1', '--owner', 'manager', '--commit', sha,
                                  '--note', 'Verified tree committed')['state'], 'done')

    def test_blocking_repair_reuses_mother_task_with_new_frozen_ticket(self):
        first = self.success_worker()
        self.create('repair-ticket')
        self.enqueue(task='repair-ticket', error='worktree_reserved')
        self.write_ticket(edit='edited\n', repair='repair-ticket')
        repair = self.enqueue(key='repair-attempt')
        frozen = Path(repair['directory']) / 'ticket.original.md'
        self.assertIn('repair-ticket', frozen.read_text())
        self.assertNotIn('repair-ticket', (Path(first['directory']) / 'ticket.original.md').read_text())
        self.assertEqual(self.completed(repair['id'])['status'], 'succeeded')
        self.completed(self.enqueue('verify', key='v')['id'])
        self.completed(self.enqueue('review', key='r')['id'])
        self.assertEqual(self.call('accept', 't1', '--owner', 'manager', '--note', 'Mother and repair checked')['state'], 'accepted')

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

    def test_silence_notifies_once_and_does_not_cancel(self):
        # tearDown opens 'gate'; a gate it never opens leaves the fixture worker polling forever.
        self.write_ticket(gate=str(self.base / 'gate'))
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.eventually(lambda: self.started.exists())
        directory = Path(attempt['directory'])
        first = subprocess.run([*CLI, '--state', str(self.state), 'wait', attempt['id'],
                                '--timeout', '5', '--silence', '0'], cwd=ROOT,
                               capture_output=True, text=True, timeout=20, env=self.env)
        self.assertEqual(first.returncode, 4, first.stderr)
        self.assertEqual(json.loads(first.stderr)['error']['code'], 'wait_silent')
        self.assertEqual(self.call('status', 't1')['state'], 'running')
        again = subprocess.run([*CLI, '--state', str(self.state), 'wait', attempt['id'],
                                '--timeout', '0.3', '--silence', '0'], cwd=ROOT,
                               capture_output=True, text=True, timeout=20, env=self.env)
        self.assertEqual(again.returncode, 3, again.stderr)
        self.assertEqual(json.loads(again.stderr)['error']['code'], 'wait_timeout')
        with open(directory / 'stdout.log', 'ab') as stream:
            stream.write(b'x')
        third = subprocess.run([*CLI, '--state', str(self.state), 'wait', attempt['id'],
                                '--timeout', '5', '--silence', '0'], cwd=ROOT,
                               capture_output=True, text=True, timeout=20, env=self.env)
        self.assertEqual(third.returncode, 4, third.stderr)
        self.assertEqual(self.call('status', 't1')['state'], 'running')

    def test_freeze_and_missing_receipt_recovery_backup(self):
        self.write_ticket(edit='partial\n', no_receipt=True)
        self.create()
        attempt = self.enqueue()
        self.write_ticket(edit='wrong\n')
        (self.skill / 'scripts/pi-runinfra-worker.sh').write_text('exit 42\n')
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

    def test_bare_no_doubt_with_punctuation_or_bullet_is_not_a_doubt(self):
        from osrelay.store import receipt_has_doubt
        path = self.base / 'receipt.md'
        for body, doubt in (('無', False), ('無。', False), ('無.', False), ('- 無', False), ('- 無。', False),
                            ('  無。  ', False), ('', False),
                            ('無。但 CDP 未驗', True), ('- 無真電話／雲端 ASR，皆未驗', True),
                            ('- 無。\n- 正式站未驗', True), ('契約沒寫清楚', True)):
            with self.subTest(body=body):
                path.write_text(f'# 回執\n## 4. 風險與存疑\n{body}\n## 5. 問答\n無\n')
                self.assertEqual(receipt_has_doubt(path), doubt)

    def test_resume_accepts_a_receipt_that_says_none_with_a_full_stop(self):
        # 2026-10-10 真機冒煙：工人照模板寫「無」但多了句號，接續被當成有存疑而拒絕。
        created = self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager',
                            '--id', 't1')
        fresh = self.enqueue()
        self.runner()
        self.assertEqual(self.completed(fresh['id'])['status'], 'succeeded')
        self.assertTrue(self.session_file(fresh['id'], created['workdir']).is_file())
        (Path(fresh['directory']) / 'receipt.md').write_text('## 4. 風險與存疑\n無。\n')
        resumed = self.enqueue(key='resume', resume=True)
        self.assertTrue(resumed['request']['resume'])
        self.assertEqual(self.completed(resumed['id'])['status'], 'succeeded')

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

    def real_pi_skill(self, ask=False):
        """The real osslab-manager pi helper and RPC driver (snapshot) with a fake RPC pi: no model call."""
        shutil.copytree(ROOT / 'tests/fixtures/real-pi', self.skill, dirs_exist_ok=True)
        secrets = self.home / '.openclaw/secrets'
        secrets.mkdir(parents=True)
        (secrets / 'glm-5.3-flash.env').write_text('GLM_53_FLASH_API_KEY=fake-key\n')
        fake = self.base / 'bin'
        fake.mkdir()
        (fake / 'pi').write_text(f"""#!{sys.executable}
import json, os, pathlib, re, sys
args = sys.argv[1:]
command = json.loads(sys.stdin.readline())
prompt = command['message']
with open(os.environ['HOME'] + '/pi-argv.jsonl', 'a') as log:
    log.write(json.dumps({{'argv': args, 'prompt': prompt, 'channel': os.environ.get('OSLAB_ASK_CHANNEL'),
                          'attempt': os.environ.get('OSRELAY_ATTEMPT')}}) + '\\n')
if '--session-dir' in args:
    d = pathlib.Path(args[args.index('--session-dir') + 1])
    (d / ('2026_' + args[args.index('--session-id') + 1] + '.jsonl')).write_text('{{}}\\n')
def ev(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)
ev(type='response', id=command.get('id'), command='prompt', success=True, data={{'disposition': 'started'}})
answer = None
if {ask!r}:
    question = {{'kind': 'scope_conflict', 'where': 'tests/x.py', 'options': ['准許改', '不改'],
                'recommendation': '准許改', 'impact': '測試段停下'}}
    ev(type='tool_execution_start', toolCallId='call_1', toolName='ask_manager', args=question)
    ev(type='extension_ui_request', id='ui-1', method='input', title='osslab-ask:call_1', placeholder='tests/x.py',
       timeout=60000)
    for line in sys.stdin:
        record = json.loads(line)
        if record.get('type') == 'extension_ui_response' and record.get('id') == 'ui-1':
            answer = record.get('value')
            break
    ev(type='tool_execution_end', toolCallId='call_1', toolName='ask_manager', isError=False, result={{}})
ticket = re.search(r'工單：(\\S+?\\.md)', prompt)[1]
receipt = re.search(r'本輪回執唯一指定路徑：([^\\n]+)', pathlib.Path(ticket).read_text())[1]
pathlib.Path('source.txt').write_text('edited\\n')
pathlib.Path(receipt).write_text('# 回執\\n## 4. 風險與存疑\\n無\\n## 5. 問答\\n' + str(answer) + '\\n')
ev(type='message_end', message={{'role': 'assistant', 'stopReason': 'stop', 'content': [{{'type': 'text', 'text': 'done'}}]}})
ev(type='agent_settled')
sys.stdin.read()
""")
        (fake / 'pi').chmod(0o700)
        self.env['PATH'] = f"{fake}:{self.env['PATH']}"
        self.call('create', '--workdir', self.repo, '--ticket', self.ticket, '--owner', 'manager', '--id', 't1')
        self.runner()

    def pi_calls(self):
        return [json.loads(line) for line in (self.home / 'pi-argv.jsonl').read_text().splitlines()]

    def test_real_pi_helper_opens_then_continues_the_session(self):
        self.real_pi_skill()
        fresh = self.enqueue()
        # Relay still reads the model route from the RPC helper's text.
        self.assertEqual((fresh['route']['model'], fresh['route']['effort'], fresh['route']['helper']),
                         ('deepseek-v4-1-flash', 'high', 'pi-runinfra-worker.sh'))
        self.assertEqual(self.completed(fresh['id'])['status'], 'succeeded')
        resumed = self.enqueue(key='resume', resume=True)
        self.assertEqual(self.completed(resumed['id'])['status'], 'succeeded')
        calls = self.pi_calls()
        self.assertEqual([c['argv'][c['argv'].index('--session-id') + 1] for c in calls], [fresh['id'], fresh['id']])
        self.assertNotIn('記憶不是證據', calls[0]['prompt'])
        self.assertIn('記憶不是證據', calls[1]['prompt'])
        self.assertIn('session=resumed(1/2', (Path(resumed['directory']) / 'stderr.log').read_text())
        # pi itself runs in RPC mode and only learns that a question channel exists.
        self.assertEqual([c['argv'][:2] for c in calls], [['--mode', 'rpc']] * 2)
        self.assertEqual([(c['channel'], c['attempt']) for c in calls], [('1', None)] * 2)

    def test_real_driver_asks_through_relay_and_delivers_the_answer(self):
        self.real_pi_skill(ask=True)
        attempt = self.enqueue()
        asked = subprocess.run([*CLI, '--state', str(self.state), 'wait', attempt['id'], '--timeout', '20'], cwd=ROOT,
                               capture_output=True, text=True, timeout=40, env=self.env)
        self.assertEqual(asked.returncode, 5, asked.stderr + (Path(attempt['directory']) / 'stderr.log').read_text())
        question = json.loads(asked.stderr)['error']['details']['questions'][0]
        self.assertEqual((question['qid'], question['question']['where']), ('call_1', 'tests/x.py'))
        self.call('answer', attempt['id'], '--qid', 'call_1', '--owner', 'manager', '--text', '准許改 tests/x.py')
        self.assertEqual(self.call('wait', attempt['id'], '--timeout', '30')['status'], 'succeeded')
        receipt = (Path(attempt['directory']) / 'receipt.md').read_text()
        self.assertIn('## 5. 問答\n准許改 tests/x.py', receipt)
        log = (Path(attempt['directory']) / 'stdout.log').read_text()
        self.assertIn('經理回覆：准許改 tests/x.py', log)
        self.assertEqual(self.call('status', 't1')['questions'][0]['state'], 'answered')

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
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
            columns = {row[1] for row in db.execute('PRAGMA table_info(tasks)')}
            self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='questions'").fetchone())
        self.assertIn('goal_id', columns)
        self.assertIn('chain', columns)
        self.assertEqual(self.enqueue(task='old', key='one')['id'], 'attempt-old')

    # --- v1.3 worker questions -------------------------------------------------

    QUESTION = {'kind': 'scope_conflict', 'where': 'tests/x.py 不在允許清單', 'options': ['准許改', '不改'],
                'recommendation': '准許改：既有斷言已過時', 'impact': '測試段停下'}

    def wait_raw(self, aid, *extra):
        return subprocess.run([*CLI, '--state', str(self.state), 'wait', aid, *map(str, extra)], cwd=ROOT,
                              capture_output=True, text=True, timeout=30, env=self.env)

    def ask_cli(self, action, aid, qid, *extra, error=None):
        return self.call('_ask', action, aid, '--qid', qid, *extra, error=error)

    def extra_task(self, name, owner, **options):
        """Another task on its own worktree, so several workers can run at once."""
        repo = self.base / ('repo-' + name)
        repo.mkdir()
        for args in [('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid')]:
            subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
        (repo / 'source.txt').write_text('initial\n')
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'fixture'], check=True)
        ticket = self.base / ('ticket-' + name + '.md')
        options['started'] = str(self.base / ('started-' + name))
        ticket.write_text(json.dumps(options) + '\nDo the fixture task.\n')
        self.call('create', '--workdir', repo, '--ticket', ticket, '--owner', owner, '--id', name)
        return self.enqueue(task=name, owner=owner)

    def test_worker_question_reported_once_and_answer_reaches_worker(self):
        result = self.base / 'ask.json'
        self.write_ticket(edit='edited\n', ask={'qid': 'call_1', 'timeout_ms': 20000,
                                                'payload': self.QUESTION, 'result': str(result)})
        self.create()
        attempt = self.enqueue()
        self.runner()
        # Once the question exists, --silence 0 makes exit 4 due at once: the question still wins.
        self.eventually(lambda: self.call('questions'))
        first = self.wait_raw(attempt['id'], '--timeout', '10', '--silence', '0')
        self.assertEqual(first.returncode, 5, first.stderr)
        error = json.loads(first.stderr)['error']
        self.assertEqual(error['code'], 'question_pending')
        self.assertIn('qid=call_1', error['message'])
        self.assertIn('kind=scope_conflict', error['message'])
        self.assertEqual(error['details']['questions'][0]['question'], self.QUESTION)
        # Reported once: waiting again does not spin on the same question, and silence (4) never masks it.
        again = self.wait_raw(attempt['id'], '--timeout', '0.5')
        self.assertEqual(again.returncode, 3, again.stderr)
        listed = self.call('questions', '--owner', 'manager')
        self.assertEqual([(q['attempt'], q['qid'], q['state']) for q in listed],
                         [(attempt['id'], 'call_1', 'pending')])
        self.assertIsNotNone(listed[0]['notified'])
        self.assertEqual(self.call('questions', '--owner', 'someone-else'), [])
        self.call('answer', attempt['id'], '--qid', 'call_1', '--owner', 'someone-else', '--text', 'x',
                  error='owner_mismatch')
        answered = self.call('answer', attempt['id'], '--qid', 'call_1', '--owner', 'manager',
                             '--text', '准許改 tests/x.py')
        self.assertEqual(answered['state'], 'answered')
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        record = json.loads(result.read_text())
        self.assertEqual((record['post'], record['poll']['state'], record['poll']['answer']),
                         (0, 'answered', '准許改 tests/x.py'))
        status = self.call('status', 't1')
        self.assertEqual([(q['qid'], q['state'], q['answered_by']) for q in status['questions']],
                         [('call_1', 'answered', 'manager')])
        kinds = [event['kind'] for event in status['events']]
        self.assertLess(kinds.index('question_asked'), kinds.index('question_answered'))
        self.call('answer', attempt['id'], '--qid', 'call_1', '--owner', 'manager', '--text', 'again',
                  error='question_expired')

    def test_wait_reports_questions_of_the_same_owner_from_other_attempts(self):
        self.write_ticket(gate=str(self.base / 'gate'))
        self.create()
        quiet = self.enqueue()
        ask = {'qid': 'call_b', 'timeout_ms': 4000, 'payload': self.QUESTION, 'result': str(self.base / 'b.json')}
        mine = self.extra_task('b', 'manager', ask=ask)
        theirs = self.extra_task('c', 'other', ask=dict(ask, qid='call_c', result=str(self.base / 'c.json')))
        self.runner()
        self.eventually(lambda: len(self.call('questions')) == 2)
        reported = self.wait_raw(quiet['id'], '--timeout', '5')
        self.assertEqual(reported.returncode, 5, reported.stderr)
        items = json.loads(reported.stderr)['error']['details']['questions']
        self.assertEqual([(q['attempt'], q['qid']) for q in items], [(mine['id'], 'call_b')])
        self.assertEqual(self.wait_raw(quiet['id'], '--timeout', '0.5').returncode, 3)
        other = self.wait_raw(theirs['id'], '--timeout', '5')
        self.assertEqual(other.returncode, 5, other.stderr)
        self.assertEqual([q['qid'] for q in json.loads(other.stderr)['error']['details']['questions']], ['call_c'])

    def test_wait_already_running_reports_a_new_question_another_wait_picked_up(self):
        # A Claude manager blocked in one foreground wait cannot read a background wait's exit 5;
        # the foreground wait must still report questions asked after it began.
        import sqlite3
        self.write_ticket(gate=str(self.base / 'gate'))
        self.create()
        quiet = self.enqueue()
        self.runner()
        self.eventually(lambda: self.call('status', 't1')['attempts'][0]['status'] == 'running')
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            # Stand-in for a background wait that reports every question the instant it is asked.
            db.execute("CREATE TRIGGER background_wait AFTER INSERT ON questions BEGIN "
                       "UPDATE questions SET notified=NEW.asked WHERE attempt_id=NEW.attempt_id AND qid=NEW.qid; END")
        blocked = subprocess.Popen([*CLI, '--state', str(self.state), 'wait', quiet['id'], '--timeout', '15'],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        time.sleep(1)
        ask = {'qid': 'call_late', 'timeout_ms': 6000, 'payload': self.QUESTION, 'result': str(self.base / 'late.json')}
        late = self.extra_task('late', 'manager', ask=ask)
        out, err = blocked.communicate(timeout=20)
        self.assertEqual(blocked.returncode, 5, err)
        items = json.loads(err)['error']['details']['questions']
        self.assertEqual([(q['attempt'], q['qid']) for q in items], [(late['id'], 'call_late')])
        self.assertIn('another wait may have reported it too', json.loads(err)['error']['message'])
        self.assertIsNotNone(items[0]['notified'])
        # A wait that starts after the question does not report it again.
        self.assertEqual(self.wait_raw(quiet['id'], '--timeout', '0.5').returncode, 3)

    def test_unanswered_question_expires_and_answer_is_refused(self):
        result = self.base / 'ask.json'
        self.write_ticket(ask={'qid': 'call_1', 'timeout_ms': 300, 'payload': self.QUESTION, 'result': str(result)})
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.eventually(lambda: result.exists())
        self.assertEqual(json.loads(result.read_text())['poll']['state'], 'expired')
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        self.call('answer', attempt['id'], '--qid', 'call_1', '--owner', 'manager', '--text', 'late',
                  error='question_expired')
        status = self.call('status', 't1')
        self.assertEqual(status['questions'][0]['state'], 'expired')
        expired = [e['body'] for e in status['events'] if e['kind'] == 'question_expired']
        self.assertEqual(expired, [{'qid': 'call_1', 'by': 'deadline'}])

    def test_open_question_is_withdrawn_when_the_attempt_finishes(self):
        result = self.base / 'ask.json'
        self.write_ticket(ask={'qid': 'call_1', 'timeout_ms': 60000, 'payload': self.QUESTION,
                               'result': str(result), 'wait': False})
        self.create()
        attempt = self.enqueue()
        self.runner()
        # The finished attempt was never waited on, so the question may or may not have been reported.
        self.eventually(lambda: self.call('status', 't1')['state'] == 'awaiting_acceptance')
        status = self.call('status', 't1')
        self.assertEqual(status['questions'][0]['state'], 'withdrawn')
        self.assertIn('question_withdrawn', [e['kind'] for e in status['events']])
        self.assertEqual(self.call('questions'), [])
        self.call('answer', attempt['id'], '--qid', 'call_1', '--owner', 'manager', '--text', 'late',
                  error='question_expired')
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')

    def test_question_channel_validates_and_is_idempotent(self):
        self.write_ticket(gate=str(self.base / 'gate'))
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.eventually(lambda: self.started.exists())
        aid = attempt['id']
        good = json.dumps(self.QUESTION)
        for qid, timeout, payload in [
                ('a b', 1000, good), ('call_1', 0, good), ('call_1', 3600001, good),
                ('call_1', 1000, json.dumps(dict(self.QUESTION, kind='production'))),
                ('call_1', 1000, json.dumps(dict(self.QUESTION, options=['only one']))),
                ('call_1', 1000, json.dumps(dict(self.QUESTION, where=' '))),
                ('call_1', 1000, '[1]'), ('call_1', 1000, 'not json')]:
            with self.subTest(qid=qid, timeout=timeout, payload=payload[:30]):
                self.ask_cli('post', aid, qid, '--timeout-ms', timeout, '--payload', payload, error='invalid_question')
        posted = self.ask_cli('post', aid, 'call_1', '--timeout-ms', 60000, '--payload', good)
        self.assertEqual(posted['state'], 'pending')
        self.assertEqual(self.ask_cli('post', aid, 'call_1', '--timeout-ms', 60000, '--payload', good)['deadline'],
                         posted['deadline'])
        self.ask_cli('post', aid, 'call_1', '--timeout-ms', 60000,
                     '--payload', json.dumps(dict(self.QUESTION, impact='other')), error='idempotency_conflict')
        self.assertEqual(self.ask_cli('expire', aid, 'call_1')['state'], 'expired')
        self.assertEqual(self.ask_cli('poll', aid, 'call_1')['state'], 'expired')
        self.ask_cli('post', aid, 'call_2', '--timeout-ms', 60000, '--payload', good)
        self.call('answer', aid, '--qid', 'call_2', '--owner', 'manager', '--text', 'ok')
        # The worker's own timeout cannot erase an answer that already arrived.
        self.assertEqual(self.ask_cli('expire', aid, 'call_2')['state'], 'answered')
        closed = [(e['kind'], e['body']['qid']) for e in self.call('status', 't1')['events'] if e['kind'].startswith('question_')]
        self.assertNotIn(('question_expired', 'call_2'), closed)
        self.ask_cli('poll', aid, 'missing', error='not_found')
        # Past the deadline with nobody polling: the answer is refused and the expiry is recorded.
        self.ask_cli('post', aid, 'call_4', '--timeout-ms', 200, '--payload', good)
        time.sleep(.3)
        self.call('answer', aid, '--qid', 'call_4', '--owner', 'manager', '--text', 'late', error='question_expired')
        self.assertEqual(self.ask_cli('poll', aid, 'call_4')['state'], 'expired')
        (self.base / 'gate').touch()
        self.assertEqual(self.completed(aid)['status'], 'succeeded')
        self.ask_cli('post', aid, 'call_3', '--timeout-ms', 60000, '--payload', good, error='attempt_not_running')

    def test_only_pi_workers_get_the_question_channel(self):
        out = self.base / 'env.json'
        self.write_ticket(edit='edited\n', env_out=str(out))
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.assertEqual(self.completed(attempt['id'])['status'], 'succeeded')
        env = json.loads(out.read_text())
        self.assertEqual(env['OSRELAY_ATTEMPT'], attempt['id'])
        self.assertEqual(env['OSRELAY_STATE'], str(self.state.resolve()))
        self.assertEqual(Path(env['OSRELAY_BIN']), ROOT / 'bin' / 'osrelay')
        out.unlink()
        glm = self.enqueue(key='glm', engine='glm')
        self.assertEqual(self.completed(glm['id'])['status'], 'succeeded')
        self.assertEqual(json.loads(out.read_text()), dict.fromkeys(env))

    def test_v2_database_upgrades_to_questions_and_v5_is_refused(self):
        import sqlite3
        self.create()
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            db.execute('DROP TABLE questions')
            db.execute('PRAGMA user_version=2')
        self.assertEqual(self.call('list')[0]['id'], 't1')
        self.assertEqual(self.call('status', 't1')['questions'], [])
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
            db.execute('PRAGMA user_version=5')
        self.call('list', error='schema_version')

    # v1.4: wait --owner and waking the bound manager.

    def fake_wake(self, mode='ok'):
        """Stand-in for paseo-wake.mjs: logs argv and stdin, answers per the mode file (ok or an error code)."""
        log, control = self.base / 'wake.log', self.base / 'wake-mode'
        control.write_text(mode)
        script = self.base / 'fake-wake'
        script.write_text(f'''#!{sys.executable}
import json, pathlib, sys
entry = {{'argv': sys.argv[1:], 'stdin': sys.stdin.read()}}
with open({str(log)!r}, 'a') as f:
    f.write(json.dumps(entry) + '\\n')
mode = pathlib.Path({str(control)!r}).read_text().strip()
if mode == 'ok':
    print(json.dumps({{'ok': True, 'status': 'running'}})); sys.exit(0)
print(json.dumps({{'ok': False, 'code': mode, 'message': 'fake ' + mode}})); sys.exit(3)
''')
        script.chmod(0o755)
        return script, log, control

    def install_skill(self):
        installed = self.home / '.agents/skills/osslab-manager'
        installed.parent.mkdir(parents=True, exist_ok=True)
        if not installed.exists():
            installed.symlink_to(self.skill, target_is_directory=True)

    def wake_log(self, log):
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def wait_owner_raw(self, owner, *extra):
        return subprocess.run([*CLI, '--state', str(self.state), 'wait', '--owner', owner, *map(str, extra)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30, env=self.env)

    def owner_report(self, owner, code, *extra):
        p = self.wait_owner_raw(owner, '--timeout', '0', *extra)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        data = json.loads(p.stderr if p.returncode else p.stdout)
        return data['error']['details'] if p.returncode else data['result']

    def ended(self, task, count=1):
        return self.eventually(lambda: (lambda a: len(a) >= count and all(
            x['status'] in ('succeeded', 'failed', 'interrupted') for x in a))(self.call('status', task)['attempts']))

    def waker(self, helper, clock):
        os.environ['OSRELAY_WAKE_HELPER'] = str(helper)
        self.addCleanup(os.environ.pop, 'OSRELAY_WAKE_HELPER', None)
        store = Store(self.state)
        self.addCleanup(store.close)
        return store, wake.Waker(store, clock=lambda: clock[0])

    def wake_round(self, waker):
        waker.start_due()
        until = time.monotonic() + 10
        while waker.busy() and time.monotonic() < until:
            waker.collect()
            time.sleep(.02)
        self.assertFalse(waker.busy())

    def test_wait_owner_reports_each_end_once_across_tasks_then_idles(self):
        self.write_ticket(edit='edited\n')
        self.create()
        first = self.enqueue()
        second = self.extra_task('b', 'manager')
        theirs = self.extra_task('c', 'other')
        self.runner()
        for task in ('t1', 'b', 'c'):
            self.ended(task)
        report = self.owner_report('manager', 0)
        self.assertEqual(sorted(a['id'] for a in report['attempts']), sorted([first['id'], second['id']]))
        self.assertEqual({a['status'] for a in report['attempts']}, {'succeeded'})
        self.assertEqual((report['questions'], report['silent'], report['running'], report['wake']), ([], [], [], None))
        self.assertNotIn('idle', report)
        again = self.owner_report('manager', 0)
        self.assertEqual((again['attempts'], again['idle']), ([], True))
        self.assertEqual([a['id'] for a in self.owner_report('other', 0)['attempts']], [theirs['id']])
        # A single-attempt wait reports that end too, so the owner view does not repeat it.
        verify = self.enqueue('verify', key='v')
        self.assertEqual(self.completed(verify['id'])['status'], 'succeeded')
        self.assertEqual(self.owner_report('manager', 0)['attempts'], [])

    def test_wait_owner_times_out_reports_silence_once_and_needs_one_target(self):
        self.write_ticket(gate=str(self.base / 'gate'))
        self.create()
        attempt = self.enqueue()
        self.runner()
        self.eventually(lambda: (self.base / 'started').exists())
        self.eventually(lambda: self.call('status', 't1')['attempts'][0]['status'] == 'running')
        running = self.owner_report('manager', 3)
        self.assertEqual((running['running'], running['attempts'], running['silent']), ([attempt['id']], [], []))
        self.assertEqual(self.owner_report('manager', 4, '--silence', '0')['silent'], [attempt['id']])
        self.assertEqual(self.owner_report('manager', 3, '--silence', '0')['silent'], [])
        self.call('wait', '--timeout', '0', error='invalid_wait')
        self.call('wait', attempt['id'], '--owner', 'manager', '--timeout', '0', error='invalid_wait')

    def test_runner_wakes_the_codex_binding_once_with_ids_only(self):
        helper, log, _ = self.fake_wake()
        self.env['OSRELAY_WAKE_HELPER'] = str(helper)
        self.write_ticket(edit='edited\n')
        self.create()
        finished = self.enqueue()
        ask = {'qid': 'call_w', 'timeout_ms': 30000, 'payload': self.QUESTION, 'result': str(self.base / 'w.json')}
        asking = self.extra_task('w', 'manager', ask=ask)
        self.runner()
        self.ended('t1')
        self.eventually(lambda: self.call('questions'))
        # Claude managers already get host notices: no wake by default.
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'claude', '--session', 'claude-1')
        time.sleep(1.5)
        self.assertEqual(self.wake_log(log), [])
        self.call('bind', 'w', '--owner', 'manager', '--runtime', 'codex', '--session', 'agent-1')
        entries = self.eventually(lambda: self.wake_log(log))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['argv'], ['send', 'agent-1'])
        text = entries[0]['stdin']
        self.assertTrue(text.startswith('[osrelay 叫醒] owner manager：'), text)
        self.assertIn('t1/worker/succeeded', text)
        self.assertIn('1 題工人發問待答', text)
        self.assertIn('osrelay wait --owner manager --timeout 0', text)
        for worker_text in (self.QUESTION['where'], self.QUESTION['recommendation'], 'Fixture completed'):
            self.assertNotIn(worker_text, text)
        # The helper logs before the runner collects its answer and records the outcome.
        sent = self.eventually(lambda: [e['body'] for e in self.call('status', 't1')['events']
                                        if e['kind'] == 'wake_sent'])
        self.assertEqual(sent, [{'session': 'agent-1', 'attempts': [finished['id']], 'questions': []}])
        sent = [e['body'] for e in self.call('status', 'w')['events'] if e['kind'] == 'wake_sent']
        self.assertEqual(sent, [{'session': 'agent-1', 'attempts': [], 'questions': ['call_w']}])
        # The manager's check: the question first (5), carrying the finished attempt in the same report.
        report = self.owner_report('manager', 5)
        self.assertEqual(([a['id'] for a in report['attempts']], [q['qid'] for q in report['questions']]),
                         ([finished['id']], ['call_w']))
        self.call('answer', asking['id'], '--qid', 'call_w', '--owner', 'manager', '--text', '准許')
        self.ended('w')
        # That end is news, but the 60-second pacing holds it for a later wake.
        time.sleep(1.5)
        self.assertEqual(len(self.wake_log(log)), 1)
        self.install_skill()
        doctor = self.call('doctor')['wake']
        self.assertEqual((doctor['enabled'], doctor['helper'], doctor['check']['ok']), (True, 'override', True))
        self.assertEqual([(b['owner'], b['session'], b['wake']) for b in doctor['bindings']],
                         [('manager', 'agent-1', 1)])
        self.assertEqual(self.wake_log(log)[-1]['argv'], ['check'])

    def test_waker_paces_merges_and_skips_what_a_wait_reported(self):
        from datetime import datetime, timedelta
        helper, log, _ = self.fake_wake()
        self.write_ticket(edit='edited\n')
        self.create()
        first = self.enqueue()
        self.runner()
        self.ended('t1')
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'codex', '--session', 'agent-1')
        clock = [datetime.fromisoformat(now())]
        store, waker = self.waker(helper, clock)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 1)
        self.assertIn('t1/worker/succeeded', self.wake_log(log)[0]['stdin'])
        verify = self.enqueue('verify', key='v')
        self.ended('t1', 2)
        review = self.enqueue('review', key='r')
        self.ended('t1', 3)
        self.wait_raw(review['id'], '--timeout', '0')  # a manager already saw the review end
        clock[0] += timedelta(seconds=10)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 1)
        clock[0] += timedelta(seconds=61)
        self.wake_round(waker)
        entries = self.wake_log(log)
        self.assertEqual(len(entries), 2)
        self.assertIn('1 個 attempt 結束（t1/verify/succeeded）', entries[1]['stdin'])
        self.assertNotIn('review', entries[1]['stdin'])
        woken = {row['id']: row['woken'] for row in store.db.execute('SELECT id,woken FROM attempts')}
        self.assertIsNotNone(woken[verify['id']])
        self.assertIsNone(woken[review['id']])
        clock[0] += timedelta(seconds=61)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 2)

    def test_waker_backs_off_never_resends_the_same_events_and_a_wait_reports_each_new_reason_once(self):
        from datetime import datetime, timedelta
        helper, log, control = self.fake_wake('agent_archived')
        self.write_ticket(edit='edited\n')
        self.create()
        first = self.enqueue()
        self.runner()
        self.ended('t1')
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'codex', '--session', 'agent-x')
        clock = [datetime.fromisoformat(now())]
        store, waker = self.waker(helper, clock)
        self.wake_round(waker)
        binding = store.binding('manager')
        self.assertEqual((binding['fail_code'], binding['fail_count']), ('agent_archived', 1))
        self.assertIsNone(store.db.execute('SELECT woken FROM attempts WHERE id=?', (first['id'],)).fetchone()[0])
        # No retry for the same event, even after the backoff: it rides along with the next new one.
        for seconds in (120, 301, 600):
            clock[0] += timedelta(seconds=seconds)
            self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 1)
        verify = self.enqueue('verify', key='v')
        self.ended('t1', 2)
        self.wake_round(waker)
        entries = self.wake_log(log)
        self.assertEqual(len(entries), 2)
        self.assertIn('2 個 attempt 結束（t1/worker/succeeded, t1/verify/succeeded）', entries[1]['stdin'])
        self.assertEqual(store.binding('manager')['fail_count'], 2)
        failed = [e['body'] for e in self.call('status', 't1')['events'] if e['kind'] == 'wake_failed']
        self.assertEqual(failed, [{'session': 'agent-x', 'attempts': [first['id']], 'questions': [],
                                   'code': 'agent_archived', 'message': 'fake agent_archived'}])
        report = self.owner_report('manager', 0)
        self.assertEqual([a['id'] for a in report['attempts']], [first['id'], verify['id']])
        self.assertEqual((report['wake']['code'], report['wake']['count'], report['wake']['session']),
                         ('agent_archived', 2, 'agent-x'))
        self.assertIsNone(self.owner_report('manager', 0)['wake'])
        control.write_text('agent_not_found')
        self.enqueue('review', key='r')
        self.ended('t1', 3)
        clock[0] += timedelta(seconds=301)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 3)
        self.assertEqual(self.owner_report('manager', 0)['wake']['code'], 'agent_not_found')
        # A new bind clears the failure.
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'codex', '--session', 'agent-y')
        binding = store.binding('manager')
        self.assertEqual((binding['fail_code'], binding['fail_count'], binding['fail_batch']), (None, 0, None))

    def test_owners_bound_to_one_session_share_one_wake_and_its_pacing(self):
        from datetime import datetime, timedelta
        helper, log, _ = self.fake_wake()
        self.write_ticket(edit='edited\n')
        self.create()
        self.enqueue()
        self.extra_task('b', 'reviewer')
        self.runner()
        self.ended('t1')
        self.ended('b')
        for task, owner in (('t1', 'manager'), ('b', 'reviewer')):
            self.call('bind', task, '--owner', owner, '--runtime', 'codex', '--session', 'agent-1')
        clock = [datetime.fromisoformat(now())]
        store, waker = self.waker(helper, clock)
        self.wake_round(waker)
        entries = self.wake_log(log)
        self.assertEqual([e['argv'] for e in entries], [['send', 'agent-1']])
        self.assertIn('owner manager：1 個 attempt 結束（t1/worker/succeeded）', entries[0]['stdin'])
        self.assertIn('owner reviewer：1 個 attempt 結束（b/worker/succeeded）', entries[0]['stdin'])
        self.assertTrue(entries[0]['stdin'].endswith('osrelay wait --owner manager --timeout 0；'
                                                     'osrelay wait --owner reviewer --timeout 0'), entries[0]['stdin'])
        self.enqueue('verify', key='v')
        self.ended('t1', 2)
        clock[0] += timedelta(seconds=30)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 1)
        clock[0] += timedelta(seconds=31)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 2)

    def test_wake_targets_the_latest_bind_and_respects_wake_off(self):
        from datetime import datetime, timedelta
        helper, log, _ = self.fake_wake()
        self.write_ticket(edit='edited\n')
        self.create()
        self.enqueue()
        self.extra_task('b', 'manager')
        self.runner()
        self.ended('t1')
        self.ended('b')
        clock = [datetime.fromisoformat(now())]
        store, waker = self.waker(helper, clock)
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'codex', '--session', 'agent-1', '--wake', 'off')
        self.wake_round(waker)
        self.assertEqual(self.wake_log(log), [])
        self.call('bind', 'b', '--owner', 'manager', '--runtime', 'claude', '--session', 'claude-2', '--wake', 'on')
        self.wake_round(waker)
        entries = self.wake_log(log)
        self.assertEqual([e['argv'] for e in entries], [['send', 'claude-2']])
        self.assertIn('2 個 attempt 結束', entries[0]['stdin'])
        # OSRELAY_WAKE_HELPER=off: nothing is sent and nothing is recorded as a failure.
        self.enqueue('verify', key='v')
        self.ended('t1', 2)
        os.environ['OSRELAY_WAKE_HELPER'] = 'off'
        clock[0] += timedelta(seconds=61)
        self.wake_round(waker)
        self.assertEqual(len(self.wake_log(log)), 1)
        self.assertIsNone(store.binding('manager')['fail_code'])

    @unittest.skipUnless(shutil.which('node'), 'the wake helper runs under node')
    def test_wake_helper_steers_only_where_paseo_will_not_interrupt(self):
        state, log = self.base / 'paseo.json', self.base / 'paseo.log'
        def agent(name, status, turn=None, archived=None):
            return {'id': name, 'status': status, 'archivedAt': archived,
                    'activeTurn': {'turnId': turn, 'startedAt': None} if turn else None}
        agents = {'idle': agent('idle', 'idle'), 'busy': agent('busy', 'running', 'codex-turn-4'),
                  'goal': agent('goal', 'running', 'autonomous-62a3'),
                  'old': agent('old', 'closed', archived='2026-10-14T00:00:00Z')}
        state.write_text(json.dumps({'connect': True, 'agents': agents}))
        env = dict(self.env, OSRELAY_PASEO_CLI=str(ROOT / 'tests/fixtures/fake-paseo-cli'),
                   FAKE_PASEO_STATE=str(state), FAKE_PASEO_LOG=str(log))

        def helper(*args, text='[osrelay 叫醒] owner m：1 個 attempt 結束\n'):
            p = subprocess.run(['node', str(ROOT / 'osrelay/paseo-wake.mjs'), *args], input=text,
                               capture_output=True, text=True, timeout=20, env=env)
            return p.returncode, json.loads(p.stdout)
        self.assertEqual(helper('check'), (0, {'ok': True}))
        self.assertEqual(helper('send', 'idle'), (0, {'ok': True, 'status': 'idle'}))
        self.assertEqual(helper('send', 'busy'), (0, {'ok': True, 'status': 'running'}))
        # A Codex /goal continuation would be interrupted, not steered; archived or missing agents are not targets.
        for name, code in (('goal', 'agent_autonomous_turn'), ('old', 'agent_archived'), ('none', 'agent_not_found')):
            exit_code, data = helper('send', name)
            self.assertEqual((exit_code, data['ok'], data['code']), (3, False, code))
        self.assertEqual(helper('send', 'idle', text='/goal pause')[1]['code'], 'invalid_message')
        self.assertEqual(helper('send')[1]['code'], 'usage')
        sent = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([(s['agentId'], s['text'], s['options']) for s in sent],
                         [(name, '[osrelay 叫醒] owner m：1 個 attempt 結束', {'activeTurnBehavior': 'steer'})
                          for name in ('idle', 'busy')])
        state.write_text(json.dumps({'connect': False, 'agents': {}}))
        exit_code, data = helper('check')
        self.assertEqual((exit_code, data['code']), (1, 'paseo_unavailable'))

    def test_wake_message_is_a_fixed_template(self):
        attempts = [{'task_id': f't{i}', 'kind': 'worker', 'status': 'failed'} for i in range(7)]
        questions = [{'deadline': '2026-10-14T03:41:00.000000+08:00'}, {'deadline': '2026-10-14T03:12:30.000000+08:00'}]
        text = wake.message([('/evil\nowner', attempts, questions)])
        self.assertTrue(text.startswith('[osrelay 叫醒] owner /evil owner：'), text)
        self.assertNotIn('\n', text)
        self.assertIn('7 個 attempt 結束（t0/worker/failed, t1/worker/failed, t2/worker/failed, t3/worker/failed, '
                      't4/worker/failed 等共 7 個）', text)
        self.assertIn('2 題工人發問待答（最早期限 03:12）', text)
        self.assertTrue(text.endswith("osrelay wait --owner '/evil owner' --timeout 0"), text)
        # Many owners on one session: a count-only notice that still fits the helper's 4000-character limit.
        crowd = [(f'owner-{i}-' + 'x' * 80, attempts, questions) for i in range(40)]
        text = wake.message(crowd)
        self.assertLessEqual(len(text), wake.MAX_MESSAGE)
        self.assertTrue(text.startswith('[osrelay 叫醒] 40 個 owner 共 280 個 attempt 結束、80 題工人發問待答。'), text)
        self.assertIn('osrelay wait --owner <owner> --timeout 0', text)

    def test_v3_upgrade_never_reports_or_wakes_history(self):
        import sqlite3
        from datetime import datetime
        helper, log, _ = self.fake_wake()
        self.write_ticket(edit='edited\n')
        self.create()
        self.enqueue()
        self.runner()
        self.ended('t1')
        runner = self.runners[0]
        runner.terminate()
        runner.wait(timeout=10)
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            for statement in ('ALTER TABLE attempts DROP COLUMN reported', 'ALTER TABLE attempts DROP COLUMN woken',
                              'ALTER TABLE questions DROP COLUMN woken', 'DROP TABLE bindings', 'PRAGMA user_version=3'):
                db.execute(statement)
        report = self.owner_report('manager', 0)
        self.assertEqual((report['attempts'], report['idle']), ([], True))
        with sqlite3.connect(self.state / 'relay.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
        self.call('bind', 't1', '--owner', 'manager', '--runtime', 'codex', '--session', 'agent-1')
        store, waker = self.waker(helper, [datetime.fromisoformat(now())])
        self.wake_round(waker)
        self.assertEqual(self.wake_log(log), [])
        self.install_skill()
        self.assertEqual(self.call('doctor')['wake'], {'enabled': False, 'helper': 'off', 'bindings': [
            dict(store.db.execute('SELECT owner,runtime,session,wake,bound_at,last_sent,last_ok,fail_at,fail_code,'
                                  'fail_message,fail_count FROM bindings').fetchone())]})

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
