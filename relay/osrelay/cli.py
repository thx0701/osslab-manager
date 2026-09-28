"""A shared CLI contract for Paseo's Codex and Claude Code sessions."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from .artifacts import RelayError, alive
from .store import Store, TERMINAL

DEFAULT_SKILL = Path.home() / '.agents/skills/osslab-manager'


def parser():
    p = argparse.ArgumentParser(prog='osrelay', description='Durable local orchestration for osslab-manager')
    p.add_argument('--state', default=os.environ.get('OSRELAY_STATE', str(Path.home() / '.local/state/osslab-relay')))
    sub = p.add_subparsers(dest='action', required=True)
    create = sub.add_parser('create', help='Register a ticket and stable owner')
    create.add_argument('--workdir', required=True)
    create.add_argument('--ticket', required=True)
    create.add_argument('--owner', required=True)
    create.add_argument('--id')
    create.add_argument('--goal', help='Parent goal id; requires --chain')
    create.add_argument('--chain', help='Chain name shared by one git worktree')
    goal = sub.add_parser('goal', help='Register the parent item that owns ticket chains')
    goal_sub = goal.add_subparsers(dest='goal_action', required=True)
    goal_create = goal_sub.add_parser('create')
    goal_create.add_argument('--id', required=True)
    goal_create.add_argument('--owner', required=True)
    goal_create.add_argument('--note', required=True)
    sub.add_parser('list')
    sub.add_parser('doctor', help='Runner and installed skill availability')
    sub.add_parser('serve', help='Foreground runner; manage with systemd or Paseo terminal')
    internal = sub.add_parser('_child', help=argparse.SUPPRESS)
    internal.add_argument('attempt'); internal.add_argument('lock_fd', type=int)
    for action in ('status', 'context', 'bind', 'run', 'review', 'verify', 'block', 'unblock', 'handoff', 'recover', 'accept', 'finalize', 'abandon'):
        sp = sub.add_parser(action)
        sp.add_argument('task')
        if action not in ('status', 'context'):
            sp.add_argument('--owner', required=True)
        if action in ('context', 'bind'):
            sp.add_argument('--runtime', choices=('codex', 'claude'), required=True)
        if action == 'bind':
            sp.add_argument('--session', required=True)
        if action in ('run', 'review', 'verify'):
            sp.add_argument('--key', required=True)
            sp.add_argument('--skill', default=str(DEFAULT_SKILL))
        if action == 'run':
            sp.add_argument('--engine', choices=('pi', 'glm'), default='pi')
            sp.add_argument('--note', help='Why this engine/attempt is selected')
            sp.add_argument('--resume', action='store_true',
                            help="Continue this task's latest pi session; refused when it cannot be continued")
        if action == 'review':
            sp.add_argument('--prompt', required=True)
        if action == 'block':
            sp.add_argument('--reason', required=True)
            sp.add_argument('--resume-note', required=True)
            sp.add_argument('--wake-condition', required=True)
        if action in ('unblock', 'recover', 'handoff', 'accept', 'finalize', 'abandon'):
            sp.add_argument('--note', required=True)
        if action == 'finalize':
            sp.add_argument('--commit', required=True, help='Manager commit SHA to verify against the accepted tree')
        if action == 'accept':
            sp.add_argument('--review-waiver', metavar='REASON',
                            help='Low-tier ticket: accept without review; refused once any review ran')
        if action == 'handoff':
            sp.add_argument('--to', required=True)
            sp.add_argument('--key', required=True)
    wait = sub.add_parser('wait', help='Wait for an attempt; timeout does not cancel it')
    wait.add_argument('attempt'); wait.add_argument('--timeout', type=float, default=30)
    cancel = sub.add_parser('cancel')
    cancel.add_argument('attempt'); cancel.add_argument('--owner', required=True); cancel.add_argument('--note', required=True)
    return p


def execute(store, args, command):
    action = args.action
    if action == 'goal':
        return store.create_goal(args.id, args.owner, args.note)
    if action == 'create':
        return store.create(args.workdir, args.ticket, args.owner, args.id, args.goal, args.chain)
    if action == 'list':
        return [dict(row) for row in store.db.execute(
            'SELECT id,workdir,owner,state,runtime,session,parent,goal_id,chain,updated FROM tasks ORDER BY created')]
    if action == 'doctor':
        from .artifacts import route
        try:
            runner = json.loads((store.root / 'runner.json').read_text())
            runner['alive'] = alive(runner['process'])
        except (OSError, ValueError, KeyError):
            runner = {'alive': False}
        return {'state': str(store.root), 'runner': runner, 'skill': str(DEFAULT_SKILL.resolve()),
                'routes': [route(DEFAULT_SKILL.resolve(), engine) for engine in ('pi', 'glm', 'grok')]}
    if action == 'serve':
        from .runner import serve
        serve(store)
        return {'stopped': True}
    if action == '_child':
        from .runner import child
        state = store.root
        store.close()
        return {'child_exit': child(state, args.attempt, args.lock_fd)}
    if action == 'context' and store.is_goal(args.task):
        return store.goal_context(args.task, args.runtime)
    if action in ('status', 'context'):
        result = store.status(args.task)
        if action == 'context':
            next_steps = {'ready': 'Inspect ticket and artifacts, then explicitly enqueue work.',
                          'running': 'Wait on the active attempt; do not duplicate it.',
                          'recovery_required': 'Inspect partial changes; recover with an inheritance note before retry.',
                          'awaiting_acceptance': 'Inspect receipt, verify and review current source, then explicitly accept.',
                          'accepted': 'Evidence checked and reservation held. Commit the accepted tree yourself, then run '
                                      'finalize <task> --owner ... --commit <sha> --note ... to close and release.',
                          'blocked': 'Read reason/resume_note/wake_condition; unblock explicitly when resolved.',
                          'done': 'Accepted. No more work on this task.',
                          'handed_off': 'Follow handed_off event to successor.',
                          'abandoned': 'Closed without acceptance; worktree released. No more work on this task.'}
            result.update({'requested_runtime': args.runtime, 'relay_state': str(store.root),
                           'next_step': next_steps[result['state']],
                           'manager_contract': 'Use osslab-manager skill; keep its model routing and human acceptance. No auto wake.'})
        return result
    if action == 'bind':
        return store.bind(args.task, args.owner, args.runtime, args.session)
    if action in ('run', 'review', 'verify'):
        return store.enqueue(args.task, args.owner, args.key, 'worker' if action == 'run' else action,
                             args.skill, engine=getattr(args, 'engine', None),
                             prompt=getattr(args, 'prompt', None), command=command,
                             note=getattr(args, 'note', None), resume=getattr(args, 'resume', False))
    if action == 'block':
        return store.block(args.task, args.owner, args.reason, args.resume_note, args.wake_condition)
    if action == 'unblock':
        return store.unblock(args.task, args.owner, args.note)
    if action == 'handoff':
        return store.handoff(args.task, args.owner, args.to, args.key, args.note)
    if action == 'recover':
        return store.recover(args.task, args.owner, args.note)
    if action == 'accept':
        return store.accept(args.task, args.owner, args.note, args.review_waiver)
    if action == 'finalize':
        return store.finalize(args.task, args.owner, args.commit, args.note)
    if action == 'abandon':
        return store.abandon(args.task, args.owner, args.note)
    if action == 'cancel':
        return store.cancel(args.attempt, args.owner, args.note)
    if action == 'wait':
        deadline = time.monotonic() + max(0, args.timeout)
        while True:
            attempt = store.attempt(args.attempt)
            if attempt['status'] in TERMINAL:
                return attempt
            if time.monotonic() >= deadline:
                raise RelayError('wait_timeout', f"{args.attempt} remains {attempt['status']}; not canceled")
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise RelayError('invalid_action', action)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = None
    if '--' in argv:
        split = argv.index('--')
        argv, command = argv[:split], argv[split + 1:]
    args = parser().parse_args(argv)
    if command is not None and args.action != 'verify':
        parser().error('Only verify accepts -- command arguments')
    store = None
    try:
        store = Store(args.state)
        value = execute(store, args, command)
        print(json.dumps({'ok': True, 'result': value}, ensure_ascii=True))
    except (RelayError, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({'ok': False, 'error': {'code': getattr(exc, 'code', 'runtime_error'),
                                              'message': str(exc)}}, ensure_ascii=True), file=sys.stderr)
        return 3 if getattr(exc, 'code', None) == 'wait_timeout' else 1
    finally:
        if store is not None:
            store.close()
    return 0
