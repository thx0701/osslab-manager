#!/bin/bash
# Fixture route: --model fixture/pi --thinking high
set -eu
# Emulates the real helper's session contract: --resume <key> opens or continues a named
# session under $HOME; --require-resume refuses (exit 3) when there is nothing to continue.
if [[ ${1:-} == --resume ]]; then
  key=$2; shift 2
  strict=
  if [[ ${1:-} == --require-resume ]]; then strict=1; shift; fi
  dir=$HOME/.local/state/osslab-manager/pi-sessions/$key-$(printf '%s' "$(readlink -f "$1")" | sha256sum | cut -c1-12)
  if [[ -n $strict ]] && ! compgen -G "$dir/*_$key.jsonl" >/dev/null; then
    echo "resume refused: no session" >&2; exit 3
  fi
  mkdir -p "$dir"; : > "$dir/fixture_$key.jsonl"
  printf '%s\n' "$key${strict:+ resumed}" >> "$HOME/fixture-pi-sessions.log"
fi
cd "$1"
python3 - "$2" <<'PY'
import json, os, pathlib, re, subprocess, sys, time
text = pathlib.Path(sys.argv[1]).read_text()
options = json.loads(text.splitlines()[0])
if options.get('edit'):
    pathlib.Path('source.txt').write_text(options['edit'])
pathlib.Path(options['started']).touch()
if options.get('env_out'):
    keys = ('OSRELAY_ATTEMPT', 'OSRELAY_STATE', 'OSRELAY_BIN')
    pathlib.Path(options['env_out']).write_text(json.dumps({key: os.environ.get(key) for key in keys}))
ask = options.get('ask')
if ask:
    # Emulates the worker driver's v1.3 channel: post, then poll until the question closes.
    channel = [os.environ['OSRELAY_BIN'], '--state', os.environ['OSRELAY_STATE'], '_ask']
    attempt = os.environ['OSRELAY_ATTEMPT']
    posted = subprocess.run(channel + ['post', attempt, '--qid', ask['qid'], '--timeout-ms', str(ask['timeout_ms']),
                                       '--payload', json.dumps(ask['payload'])], capture_output=True, text=True)
    record = {'post': posted.returncode}
    while ask.get('wait', True) and posted.returncode == 0:
        polled = subprocess.run(channel + ['poll', attempt, '--qid', ask['qid']], capture_output=True, text=True)
        record['poll'] = json.loads(polled.stdout)['result']
        if record['poll']['state'] != 'pending':
            break
        time.sleep(.05)
    pathlib.Path(ask['result']).write_text(json.dumps(record))
if options.get('gate'):
    while not pathlib.Path(options['gate']).exists():
        time.sleep(.05)
if not options.get('no_receipt'):
    path = re.search(r'本輪回執唯一指定路徑：([^\n]+)', text)[1]
    pathlib.Path(path).write_text('Fixture completed; manager must verify.\n')
sys.exit(options.get('exit', 0))
PY
