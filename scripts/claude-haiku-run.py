#!/usr/bin/env python3
"""Run one Claude Code subscription worker and fail unless the init model matches."""
import json
import os
import re
import signal
import subprocess
import sys

EXPECTED_MODEL = "claude-haiku-5-5"
API_KEY_AUTH = {"ANTHROPIC_API_KEY", "apiKeyHelper"}
MODEL_LABEL = re.compile(r"[A-Za-z0-9._:-]{1,64}")
# Claude Code may emit UI system events (e.g. ui_invalidate) before init; skip at most this many.
PRE_INIT_LIMIT = 20


def label(value):
    if isinstance(value, str) and MODEL_LABEL.fullmatch(value):
        return value
    return "rejected"


def stop(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    except ProcessLookupError:
        proc.wait()


def reject(proc, message):
    stop(proc)
    print(message, file=sys.stderr)
    return 1


def run(workdir, prompt, cli):
    proc = subprocess.Popen(
        [cli, "-p",
         "--output-format", "stream-json",
         "--verbose",
         "--safe-mode",
         "--model", EXPECTED_MODEL,
         "--effort", "high",
         "--disable-slash-commands",
         "--strict-mcp-config",
         "--no-session-persistence",
         "--permission-mode", "bypassPermissions",
         "--dangerously-skip-permissions",
         prompt],
        cwd=workdir,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=None,
        start_new_session=True,
        text=True,
    )
    try:
        # Hold earlier system events until init passes the checks; any other event before init means
        # the worker started without a verified model and login, so reject it.
        held = []
        while True:
            line = proc.stdout.readline()
            try:
                event = json.loads(line) if line else None
            except ValueError:
                event = None
            if not isinstance(event, dict) or event.get("type") != "system" or len(held) > PRE_INIT_LIMIT:
                return reject(proc, "claude worker rejected: model=missing")
            if event.get("subtype") == "init":
                break
            held.append(line)
        if event.get("model") != EXPECTED_MODEL:
            return reject(proc, "claude worker rejected: model=" + label(event.get("model")))
        if event.get("apiKeySource") in API_KEY_AUTH:
            return reject(proc, "claude worker rejected: auth=ANTHROPIC_API_KEY")
        sys.stdout.writelines(held)
        sys.stdout.write(line)
        sys.stdout.flush()
        seen = set()
        while True:
            chunk = proc.stdout.readline()
            if not chunk:
                break
            sys.stdout.write(chunk)
            sys.stdout.flush()
            try:
                event = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                usage = event.get("modelUsage")
                if isinstance(usage, dict):
                    seen.update(key for key in usage if isinstance(key, str))
        code = proc.wait()
        if code == 0 and EXPECTED_MODEL not in seen:
            other = next(iter(seen), None)
            print("claude worker rejected: model=" + (label(other) if other else "missing"), file=sys.stderr)
            return 1
        return code if code >= 0 else 1
    finally:
        stop(proc)


def main():
    if len(sys.argv) != 4:
        print("usage: claude-haiku-run.py <workdir> <prompt> <claude-bin>", file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        return run(*sys.argv[1:])
    except KeyboardInterrupt:
        print("claude worker interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
