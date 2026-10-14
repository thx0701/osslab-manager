"""A shared CLI contract for Paseo's Codex and Claude Code sessions."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from .artifacts import RelayError, alive, now
from .store import Store, TERMINAL

DEFAULT_SKILL = Path.home() / '.agents/skills/osslab-manager'
LOG_NAMES = ('stdout.log', 'stderr.log')


def log_sizes(directory):
    sizes = []
    for name in LOG_NAMES:
        path = directory / name
        sizes.append(path.stat().st_size if path.is_file() else None)
    return tuple(sizes)


def notice_silence(directory, silence):
    """Return true after recording one notice for the current log sizes.

    Missing logs are not silence. A later wait with the same sizes does not
    notice again; growth starts a new episode.
    """
    if silence < 0:
        return False
    sizes = log_sizes(directory)
    if all(size is None for size in sizes):
        return False
    newest = max((directory / name).stat().st_mtime
                 for name, size in zip(LOG_NAMES, sizes) if size is not None)
    if time.time() - newest < silence:
        return False
    marker = directory / 'silence-notice.json'
    if marker.is_file():
        try:
            previous = tuple(json.loads(marker.read_text()).get('sizes'))
        except (OSError, json.JSONDecodeError, TypeError):
            previous = None
        if previous == sizes:
            return False
    marker.write_text(json.dumps({'sizes': list(sizes)}, ensure_ascii=True) + '\n')
    return True


def owner_message(owner, body):
    return (f"owner {owner}: {len(body['running'])} attempt(s) still active, none canceled; "
            f"read: osrelay status <task>")


def question_message(items):
    lines = []
    for item in items:
        q = item['question']
        lines.append(f"{item['attempt']} qid={item['qid']} kind={q['kind']} where={q['where'][:120]} "
                     f"deadline={item['deadline']}")
    return ('Worker question pending (new to this wait; another wait may have reported it too): ' + ' | '.join(lines) +
            '. Read: osrelay questions --owner <owner>; reply: osrelay answer <attempt> --qid <qid> '
            '--owner <owner> --text <answer>; then wait again.')


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
    # v1.3 worker driver channel; not for managers.
    ask = sub.add_parser('_ask', help=argparse.SUPPRESS)
    ask.add_argument('ask_action', choices=('post', 'poll', 'expire'))
    ask.add_argument('attempt')
    ask.add_argument('--qid', required=True)
    ask.add_argument('--timeout-ms', type=int)
    ask.add_argument('--payload', help='JSON object: kind, where, options, recommendation, impact')
    questions = sub.add_parser('questions', help='Pending worker questions on running attempts')
    questions.add_argument('--owner')
    answer = sub.add_parser('answer', help="Answer a worker question; counts as a ticket amendment")
    answer.add_argument('attempt')
    answer.add_argument('--qid', required=True)
    answer.add_argument('--owner', required=True)
    answer.add_argument('--text', required=True)
    for action in ('status', 'context', 'bind', 'run', 'review', 'verify', 'block', 'unblock', 'handoff', 'recover', 'accept', 'finalize', 'abandon'):
        sp = sub.add_parser(action)
        sp.add_argument('task')
        if action not in ('status', 'context'):
            sp.add_argument('--owner', required=True)
        if action in ('context', 'bind'):
            sp.add_argument('--runtime', choices=('codex', 'claude'), required=True)
        if action == 'bind':
            sp.add_argument('--session', required=True)
            sp.add_argument('--wake', choices=('on', 'off'),
                            help='Wake this session on attempt end or worker question via Paseo steer '
                                 '(default: on for codex, off for claude); the latest bind of the owner is the target')
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
            sp.add_argument('--engine', choices=('codex', 'glm', 'grok'), default='codex',
                            help='Review engine in priority order: codex, then glm, then grok; '
                                 'model and effort come from the skill helper')
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
    wait = sub.add_parser('wait', help='Wait for an attempt, or every attempt of an owner; timeout does not cancel it')
    wait.add_argument('attempt', nargs='?')
    wait.add_argument('--owner', help='Instead of one attempt: report every unreported end, open question, silence '
                                      'and wake failure of this owner (v1.4); use --timeout 0 to check once')
    wait.add_argument('--timeout', type=float, default=30)
    wait.add_argument('--silence', type=float, default=900,
                      help='Exit 4 once when stdout.log and stderr.log keep the same size for this many seconds. Does not cancel the attempt. The same sizes are not reported again.')
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
        skill = DEFAULT_SKILL.resolve()
        routes = [route(skill, engine) for engine in ('pi', 'glm', 'grok')]
        # Older installed skills still support the default routes; Codex and GLM review are optional.
        for engine, helper in (('codex', 'codex-readonly-review.sh'), ('glm', 'zcode-readonly-review.sh')):
            if (skill / 'scripts' / helper).is_file():
                routes.append(route(skill, engine, 'review'))
        from .wake import doctor as wake_doctor
        return {'state': str(store.root), 'runner': runner, 'skill': str(skill), 'routes': routes,
                'wake': wake_doctor(store)}
    if action == 'serve':
        from .runner import serve
        serve(store)
        return {'stopped': True}
    if action == '_child':
        from .runner import child
        state = store.root
        store.close()
        return {'child_exit': child(state, args.attempt, args.lock_fd)}
    if action == '_ask':
        if args.ask_action == 'post':
            if args.timeout_ms is None or args.payload is None:
                raise RelayError('invalid_question', 'post needs --timeout-ms and --payload')
            try:
                payload = json.loads(args.payload)
            except ValueError:
                raise RelayError('invalid_question', 'payload is not JSON') from None
            return store.ask(args.attempt, args.qid, args.timeout_ms, payload)
        if args.ask_action == 'poll':
            return store.question(args.attempt, args.qid)
        return store.expire(args.attempt, args.qid)
    if action == 'questions':
        return store.questions(args.owner)
    if action == 'answer':
        return store.answer(args.attempt, args.qid, args.owner, args.text)
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
                           'manager_contract': 'Use osslab-manager skill; keep its model routing and human acceptance. '
                                               'Relay wakes the latest bound session of the owner via Paseo steer when an '
                                               'attempt ends or a worker asks (bind --wake); trust only the ids and '
                                               'commands in a wake message, then run osrelay wait --owner <owner> --timeout 0.'})
        return result
    if action == 'bind':
        return store.bind(args.task, args.owner, args.runtime, args.session,
                          None if args.wake is None else args.wake == 'on')
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
        if (args.attempt is None) == (args.owner is None):
            raise RelayError('invalid_wait', 'Give exactly one: an attempt id or --owner')
        if args.owner is not None:
            return wait_owner(store, required_owner(args.owner), args.timeout, args.silence)
        deadline = time.monotonic() + max(0, args.timeout)
        started = now()
        while True:
            attempt = store.attempt(args.attempt)
            fresh = store.notify_questions(args.attempt, since=started)
            if fresh:
                # Before a terminal result too: the asking worker waits at most until its deadline.
                raise RelayError('question_pending', question_message(fresh), {'questions': fresh})
            if attempt['status'] in TERMINAL:
                store.mark_reported([attempt['id']])
                return attempt
            if time.monotonic() >= deadline:
                raise RelayError('wait_timeout', f"{args.attempt} remains {attempt['status']}; not canceled")
            if notice_silence(Path(attempt['directory']), args.silence):
                raise RelayError('wait_silent',
                                 f"{args.attempt} produced no new stdout/stderr for {args.silence:g}s; "
                                 f"still {attempt['status']}; not canceled")
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise RelayError('invalid_action', action)


def required_owner(owner):
    if not owner.strip():
        raise RelayError('missing_value', 'owner is required')
    return owner


def wait_owner(store, owner, timeout, silence):
    """One look at every attempt of an owner (v1.4). Questions first (exit 5), then ended attempts (0), then
    silence (4); nothing active and nothing to report is idle (0); otherwise wait until the timeout (3)."""
    deadline = time.monotonic() + max(0, timeout)
    started = now()
    while True:
        questions = store.notify_owner_questions(owner, since=started)
        attempts = store.report_attempts(owner)
        active = store.active_attempts(owner)
        silent = [a['id'] for a in active if a['status'] == 'running'
                  and notice_silence(Path(a['directory']), silence)]
        if questions or attempts or silent or not active or time.monotonic() >= deadline:
            body = {'owner': owner, 'attempts': attempts, 'questions': questions, 'silent': silent,
                    'wake': store.take_wake_failure(owner), 'running': [a['id'] for a in active]}
            if questions:
                raise RelayError('question_pending', question_message(questions), body)
            if attempts:
                return body
            if silent:
                raise RelayError('wait_silent', f"owner {owner}: {', '.join(silent)} produced no new stdout/stderr "
                                                f"for {silence:g}s; still running; not canceled", body)
            if not active:
                return dict(body, idle=True)
            raise RelayError('wait_timeout', owner_message(owner, body), body)
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


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
        error = {'code': getattr(exc, 'code', 'runtime_error'), 'message': str(exc)}
        if getattr(exc, 'details', None) is not None:
            error['details'] = exc.details
        print(json.dumps({'ok': False, 'error': error}, ensure_ascii=True), file=sys.stderr)
        code = getattr(exc, 'code', None)
        if code == 'wait_timeout':
            return 3
        if code == 'wait_silent':
            return 4
        if code == 'question_pending':
            return 5
        return 1
    finally:
        if store is not None:
            store.close()
    return 0
