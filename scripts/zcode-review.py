#!/usr/bin/env python3
"""One fresh read-only ZCode review through its native stdio protocol."""
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from zoneinfo import ZoneInfo


class ReviewError(Exception):
    pass


class Backend:
    def __init__(self, cli, workdir, runtime):
        env = dict(os.environ, ZCODE_STORAGE_DIR=str(runtime),
                   ZCODE_SESSION_DB_PATH=str(runtime / 'sessions.sqlite'))
        self.proc = subprocess.Popen(
            ['node', cli, 'app-server', '--stdio'], cwd=workdir, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, start_new_session=True)
        self.queue = queue.Queue()
        self.events = deque()
        self.sequence = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                self.queue.put(message)
        self.queue.put(None)

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + '\n')
        self.proc.stdin.flush()

    def receive(self, timeout):
        try:
            message = self.queue.get(timeout=max(.01, timeout))
        except queue.Empty:
            raise ReviewError('ZCode response timed out') from None
        if message is None:
            raise ReviewError('ZCode backend exited before completion')
        if 'id' in message and 'method' in message:
            if message['method'] == 'session/requestRuntimePreferences':
                self.send({'id': message['id'], 'result': {
                    'nativeSearchEnhancementsEnabled': False, 'memoryEnabled': False,
                    'askUserQuestionAutoResolutionEnabled': False}})
            else:
                self.send({'id': message['id'], 'error': {
                    'code': -32601, 'message': 'Read-only reviewer cannot approve interactions'}})
                raise ReviewError('ZCode requested an unsupported interaction')
        return message

    def request(self, method, params, timeout=30):
        self.sequence += 1
        request_id = self.sequence
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.receive(deadline - time.monotonic())
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    # Backend errors can include provider credentials; never copy raw errors to logs.
                    raise ReviewError(f'ZCode {method} failed')
                return message.get('result', {})
            self.remember(message)
        raise ReviewError(f'ZCode {method} timed out')

    def remember(self, message):
        if message.get('method') == 'session/event':
            event = message.get('params', {})
            if event.get('type') in ('turn.completed', 'turn.failed'):
                self.events.append(event)

    def completed(self, session_id, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.events:
                event = self.events.popleft()
            else:
                self.remember(self.receive(deadline - time.monotonic()))
                continue
            if event.get('sessionId') != session_id:
                continue
            if event.get('type') != 'turn.completed' or event.get('payload', {}).get('resultType') != 'success':
                raise ReviewError('ZCode review did not finish successfully')
            return
        raise ReviewError('ZCode review timed out')

    def close(self):
        # Only our own backend process group; never touch existing ZCode sessions.
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        except ProcessLookupError:
            self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()


def check_settings(snapshot):
    settings = snapshot.get('settings', {})
    model = settings.get('model', {}).get('current', {})
    if model.get('modelId') != 'GLM-5.3' or model.get('providerId') != 'anthropic':
        raise ReviewError('ZCode did not select GLM-5.3 on the Coding Plan route')
    if settings.get('thoughtLevel', {}).get('current') != 'high':
        raise ReviewError('ZCode did not enable High thinking')
    if settings.get('mode', {}).get('current') != 'plan':
        raise ReviewError('ZCode did not enable read-only plan mode')


def review(workdir, prompt_file, cli, timeout=900):
    state = Path.home() / '.local/state/osslab-manager/zcode-reviews'
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix='review-', dir=state))
    backend = Backend(cli, workdir, runtime)
    session_id = None
    try:
        workspace = {'workspacePath': str(Path(workdir).resolve()),
                     'workspaceKey': str(Path(workdir).resolve())}
        result = backend.request('session/create', {
            'workspace': workspace, 'mode': 'plan', 'thoughtLevel': 'high',
            'titleGenerationEnabled': False, 'toolAllowlist': ['Read', 'Grep']})
        session_id = result.get('session', {}).get('sessionId')
        if not session_id:
            raise ReviewError('ZCode returned no session ID')
        backend.request('session/setThoughtLevel', {
            'sessionId': session_id, 'thoughtLevel': 'high', 'persistAsWorkspaceLastUsed': False})
        check_settings(backend.request('session/read', {'sessionId': session_id}))
        backend.request('session/subscribe', {
            'sessionId': session_id, 'deliveryKind': 'desktop-continuous',
            'includeSnapshot': False, 'afterSeq': 0})
        prompt = ('你是唯讀審查員。只用 Read/Grep，不改檔、不派工、不讀秘密。'
                  '請依下列審查包列出成立問題；沒問題直說。\n\n' + Path(prompt_file).read_text())
        result = backend.request('session/send', {'sessionId': session_id, 'content': prompt})
        if result.get('accepted') is not True:
            raise ReviewError('ZCode did not accept the review prompt')
        backend.completed(session_id, timeout)
        check_settings(backend.request('session/read', {'sessionId': session_id}))
        messages = backend.request('session/messages', {'sessionId': session_id}).get('messages', [])
        reports = ['\n'.join(p.get('text', '') for p in m.get('parts', []) if p.get('type') == 'text').strip()
                   for m in messages if m.get('info', {}).get('role') == 'assistant']
        # An empty final response must not fall back to earlier progress commentary.
        report = reports[-1] if reports else ''
        if not report:
            raise ReviewError('ZCode returned an empty review report')
        timestamp = datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')
        return f'審查：zcode / GLM-5.3 high @ {timestamp}\n\n{report}\n'
    finally:
        if session_id:
            try:
                backend.request('session/close', {'sessionId': session_id}, timeout=3)
            except (ReviewError, OSError):
                pass
        backend.close()


def main():
    if len(sys.argv) != 4:
        print('usage: zcode-review.py <workdir> <prompt-file> <zcode-cli>', file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        print(review(*sys.argv[1:]), end='')
        return 0
    except KeyboardInterrupt:
        print('ZCode review interrupted', file=sys.stderr)
        return 130
    except (ReviewError, OSError, ValueError):
        print('ZCode review failed; model/High/read-only/completion could not be verified', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
