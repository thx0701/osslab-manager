#!/usr/bin/env python3
"""用法：pi-worker-driver.py --prompt <送單指示全文> -- <pi 執行檔> <pi 參數…>（參數須含 --mode rpc）

pi 工人的 RPC 驅動程式。以 RPC 模式啟動 pi、用 `prompt` 指令送出送單指示，`agent_settled` 後關閉 pi 的
stdin 讓它收尾。跑的過程中把事件濃縮成一行一筆、立即寫進 stdout（Relay 的 900 秒靜默警報才分得出卡住
還是在跑）；結束時照文字模式印最後一則回覆全文，並照文字模式決定成敗：

- pi 非零退出原樣回傳；被訊號砍掉的換成 128＋訊號編號。
- 整場最後一則模型回覆的 stopReason 是 error／aborted：錯誤訊息寫 stderr，exit 1（pi 自己仍回 0）。
- pi 回 0 卻沒有任何模型回覆（含 prompt 被拒）：exit 1。

濃縮行只寫工具名與主要參數前 80 字（workdir 路徑縮成 . 與相對路徑，否則前 80 字常被 cd 的絕對路徑吃光）、
耗時、停止原因、token 數；思考、文字片段與工具輸出一律不寫。不認得的事件與欄位異常的事件只跳過那一筆；
不是事件格式的行原樣轉出。

施工中發問（Relay v1.3）：ask 擴充（pi-ask-manager.ts）以標題 `osslab-ask:<toolCallId>` 的對話框發問；
本程序從事件流找回該次呼叫的完整參數，經 Relay `_ask post` 登記、每 5 秒 `_ask poll`，拿到答案寫回 pi 的
stdin。pi 端對話框逾時（該工具先結束）就 `_ask expire`。Relay 通道（OSRELAY_ATTEMPT／STATE／BIN）
只給本程序，不傳給 pi；pi 只拿到 `OSLAB_ASK_CHANNEL=1` 表示有通道。其他對話框一律回 cancelled。

本程序就是起跑行 pid= 記的那個程序，pi 是它的子程序：收到 SIGTERM／SIGINT／SIGHUP 轉給 pi；
本程序不論怎麼死，pi 都會因 PDEATHSIG 收到 SIGTERM，不會變成孤兒繼續改工作樹。
"""

import ctypes
import hashlib
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# 台灣沒有日光節約；固定位移，不依賴環境的 TZ 與系統時區資料。
TAIPEI = timezone(timedelta(hours=8))
FORWARDED = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
PR_SET_PDEATHSIG = 1
ARG_KEYS = ("command", "path", "file_path", "pattern", "query", "url")
# pi 已結束但孫程序還開著它的 stdout 時，最多再收這麼久就收尾，不陪孫程序等下去。
DRAIN_SECONDS = 2.0
# 關閉 stdin 後 pi 該自己收尾；超過這麼久還沒退出就送 SIGTERM。
SHUTDOWN_GRACE = 60.0
POLL_SECONDS = 5.0
ASK_TOOL = "ask_manager"
ASK_PREFIX = "osslab-ask:"
ASK_FIELDS = ("kind", "where", "options", "recommendation", "impact")
DIALOGS = ("select", "confirm", "input", "editor")
CHANNEL = ("OSRELAY_ATTEMPT", "OSRELAY_STATE", "OSRELAY_BIN")

child = None


def emit(text):
    sys.stdout.buffer.write(text.encode("utf-8", "replace") + b"\n")
    sys.stdout.buffer.flush()


def note(text):
    emit(f"{datetime.now(TAIPEI):%H:%M:%S} {text}")


def warn(text):
    print(f"pi-worker-driver: {text}", file=sys.stderr, flush=True)


def clip(text, limit=80):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def first_line(text):
    return (str(text).strip().splitlines() or [""])[0]


def qid_for(call_id):
    """Relay 只收 [A-Za-z0-9_.:-]{1,128}；不合格的 toolCallId 改用 sha256 前 16 碼。"""
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", call_id):
        return call_id
    return hashlib.sha256(call_id.encode()).hexdigest()[:16]


class Relay:
    """Relay v1.3 的 `_ask` 子指令；呼叫失敗回 None，由呼叫端退回現行行為。"""

    def __init__(self, env):
        self.attempt, self.state, self.bin = (env.get(key) for key in CHANNEL)
        self.available = bool(self.attempt and self.state and self.bin and os.access(self.bin, os.X_OK))

    def call(self, action, qid, *extra):
        argv = [self.bin, "--state", self.state, "_ask", action, self.attempt, "--qid", qid, *extra]
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
            data = json.loads(done.stderr if done.returncode else done.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            warn(f"Relay _ask {action} 失敗：{exc!r}")
            return None
        if done.returncode or not isinstance(data, dict) or not data.get("ok"):
            warn(f"Relay _ask {action} 失敗：{clip(json.dumps(data, ensure_ascii=False), 300)}")
            return None
        return data.get("result")


class Stream:
    def __init__(self, relay):
        self.relay = relay
        self.last_reply = None
        self.tools = {}
        # helper 已 cd 到 workdir 才 exec 本程序。
        self.workdir = os.getcwd().rstrip("/")
        self.outbox = b""
        self.settled = False
        self.ask_args = {}
        # 等答案中的對話框：request id → {call, qid, next}
        self.waiting = {}

    def send(self, record):
        self.outbox += json.dumps(record, ensure_ascii=False).encode() + b"\n"

    def answer(self, request_id, value=None):
        """回覆 pi 的對話框；沒有值就是 cancelled，擴充會照「沒有收到經理回覆」處理。"""
        record = {"type": "extension_ui_response", "id": request_id}
        record.update({"value": value} if value is not None else {"cancelled": True})
        self.send(record)

    def line(self, raw):
        """一行 stdout：事件就濃縮，不是事件格式就原樣轉出。"""
        try:
            event = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            event = None
        if not (isinstance(event, dict) and isinstance(event.get("type"), str)):
            sys.stdout.buffer.write(raw + b"\n")
            sys.stdout.buffer.flush()
            return
        handler = getattr(self, "on_" + event["type"], None)
        if not handler:
            return
        try:
            handler(event)
        except Exception as exc:
            # 單一事件欄位異常只跳過那一筆，不為了濃縮行砍掉跑到一半的工人。
            warn(f"跳過無法處理的 {event['type']} 事件：{exc!r}")

    def on_response(self, event):
        if event.get("command") != "prompt":
            return
        if not event.get("success"):
            warn(f"prompt 被拒：{first_line(event.get('error', ''))}")
            self.settled = True
        elif (event.get("data") or {}).get("disposition") == "handled":
            self.settled = True

    def on_agent_settled(self, event):
        self.settled = True

    def on_tool_execution_start(self, event):
        name = event.get("toolName") or "tool"
        self.tools[event.get("toolCallId")] = (name, time.monotonic())
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        if name == ASK_TOOL:
            self.ask_args[event.get("toolCallId")] = args
            note(f"發問（{args.get('kind')}）：{clip(self.relative(str(args.get('where', ''))))}")
            return
        main = next((args[key] for key in ARG_KEYS if isinstance(args.get(key), str)), "")
        main = self.relative(main)
        note(f"{name}: {clip(main)}" if main else name)

    def relative(self, text):
        if self.workdir:
            return text.replace(self.workdir + "/", "").replace(self.workdir, ".")
        return text

    def on_tool_execution_end(self, event):
        call = event.get("toolCallId")
        for request_id, item in list(self.waiting.items()):
            if item["call"] == call:
                # pi 端對話框先逾時：不再等，Relay 記成逾時（已答的題目 Relay 保留 answered）。
                del self.waiting[request_id]
                self.relay.call("expire", item["qid"])
                note(f"發問逾時（{item['qid']}）")
        name, started = self.tools.pop(call, (event.get("toolName") or "tool", None))
        took = f" {time.monotonic() - started:.1f}s" if started is not None else ""
        note(f"{name} {'失敗' if event.get('isError') else '完成'}{took}")

    def on_extension_ui_request(self, event):
        if event.get("method") not in DIALOGS:
            return  # notify／setStatus 這類不需回應
        request_id = event.get("id")
        title = str(event.get("title", ""))
        call = title[len(ASK_PREFIX):] if event.get("method") == "input" and title.startswith(ASK_PREFIX) else None
        args = self.ask_args.get(call) if call is not None else None
        # 逾時只在擴充定義一次，pi 會帶在請求裡；沒帶就不是我們的發問。
        timeout = event.get("timeout")
        if args is None or not self.relay.available or not isinstance(timeout, int) or timeout <= 0:
            warn(f"非預期的對話框，回 cancelled：{clip(title)}")
            self.answer(request_id)
            return
        qid = qid_for(call)
        payload = {key: args.get(key) for key in ASK_FIELDS}
        result = self.relay.call("post", qid, "--timeout-ms", str(timeout),
                                 "--payload", json.dumps(payload, ensure_ascii=False))
        if result is None:
            self.answer(request_id)
            note(f"發問未送達經理（{qid}）")
            return
        self.waiting[request_id] = {"call": call, "qid": qid, "next": time.monotonic() + POLL_SECONDS}
        deadline = str(result.get("deadline", ""))[11:19]
        note(f"等經理回覆（{qid}，截止 {deadline}）")

    def poll(self):
        now = time.monotonic()
        for request_id, item in list(self.waiting.items()):
            if item["next"] > now:
                continue
            item["next"] = now + POLL_SECONDS
            result = self.relay.call("poll", item["qid"])
            if result is None or result.get("state") == "pending":
                continue
            del self.waiting[request_id]
            if result.get("state") == "answered" and isinstance(result.get("answer"), str):
                self.answer(request_id, result["answer"])
                note(f"經理回覆：{clip(result['answer'])}")
            else:
                self.answer(request_id)
                note(f"發問結束沒有回覆（{item['qid']}：{result.get('state')}）")

    def next_poll(self):
        if not self.waiting:
            return None
        return min(item["next"] for item in self.waiting.values())

    def on_message_end(self, event):
        message = event.get("message")
        if not (isinstance(message, dict) and message.get("role") == "assistant"):
            return
        # 先錯後重試成功時，以最後一則為準。
        self.last_reply = message
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        note(f"回覆 stop={message.get('stopReason')} in={usage.get('input', '?')} out={usage.get('output', '?')}")

    def on_auto_retry_start(self, event):
        note(f"重試 {event.get('attempt')}/{event.get('maxAttempts')}，"
             f"等 {(event.get('delayMs') or 0) / 1000:.0f}s：{clip(first_line(event.get('errorMessage', '')), 120)}")

    def on_auto_retry_end(self, event):
        if event.get("success"):
            note(f"重試成功（第 {event.get('attempt')} 次）")
        else:
            note(f"重試放棄：{clip(first_line(event.get('finalError', '')), 120)}")

    def on_compaction_start(self, event):
        note(f"壓縮 context（{event.get('reason')}）")

    def on_compaction_end(self, event):
        if event.get("aborted"):
            note("壓縮中止")
        elif event.get("errorMessage"):
            note(f"壓縮失敗：{clip(first_line(event['errorMessage']), 120)}")
        else:
            note("壓縮完成")

    def on_summarization_retry_scheduled(self, event):
        note(f"壓縮重試 {event.get('attempt')}/{event.get('maxAttempts')}")

    def finish(self, code):
        """pi 已退出：照文字模式印最後回覆並決定結束碼。"""
        if code != 0:
            return code
        reply = self.last_reply
        if reply is None:
            warn("pi 結束但沒有任何模型回覆")
            return 1
        if reply.get("stopReason") in ("error", "aborted"):
            print(reply.get("errorMessage") or f"Request {reply.get('stopReason')}", file=sys.stderr, flush=True)
            return 1
        note("最後回覆：")
        for block in reply.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                emit(block.get("text", ""))
        return 0


def forward(signum, frame):
    if child is None:
        # pi 還沒起來：照被砍的慣例退出，不留下半啟動的子程序。
        os._exit(128 + signum)
    try:
        child.send_signal(signum)
    except ProcessLookupError:
        pass


def die_with_parent(libc, parent):
    def setup():
        if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
            os._exit(126)
        # fork 之後、prctl 之前父程序就死了，PDEATHSIG 不會再送：自己了斷。
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGTERM)
    return setup


def pump(stream):
    """讀 pi 的 stdout、寫它的 stdin、輪詢 Relay，直到 stdout 關閉；pi 退出後只再收 DRAIN_SECONDS。"""
    out_fd, in_fd = child.stdout.fileno(), child.stdin.fileno()
    os.set_blocking(in_fd, False)
    stdin_open = True
    closed_at = None
    pending = b""
    deadline = None
    while True:
        now = time.monotonic()
        if deadline is None and child.poll() is not None:
            deadline = now + DRAIN_SECONDS
        if deadline is not None and now >= deadline:
            break
        if stdin_open and stream.settled and not stream.outbox:
            child.stdin.close()
            stdin_open, closed_at = False, now
        if closed_at is not None and deadline is None and now - closed_at > SHUTDOWN_GRACE:
            warn("關閉 stdin 後 pi 沒有退出，送 SIGTERM")
            child.terminate()
            closed_at = None
        waits = [1.0]
        if deadline is not None:
            waits.append(deadline - now)
        if stream.next_poll() is not None:
            waits.append(stream.next_poll() - now)
        writers = [in_fd] if stdin_open and stream.outbox else []
        readable, writable, _ = select.select([out_fd], writers, [], max(0.0, min(waits)))
        if writable:
            try:
                written = os.write(in_fd, stream.outbox)
                stream.outbox = stream.outbox[written:]
            except BlockingIOError:
                pass
            except BrokenPipeError:
                stream.outbox = b""
        if readable:
            chunk = os.read(out_fd, 65536)
            if not chunk:
                break
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for raw in lines:
                stream.line(raw.removesuffix(b"\r"))
        # 先處理 pi 已送來的事件再輪詢：pi 端對話框已逾時（工具已結束）就不會再把答案寫給它。
        stream.poll()
    if pending:
        stream.line(pending.removesuffix(b"\r"))
    if stdin_open:
        try:
            child.stdin.close()
        except BrokenPipeError:
            pass


def main(argv):
    global child
    if len(argv) < 5 or argv[1] != "--prompt" or argv[3] != "--":
        print("usage: pi-worker-driver.py --prompt <text> -- <pi> <pi args…>", file=sys.stderr)
        return 2
    prompt, command = argv[2], argv[4:]
    for signum in FORWARDED:
        signal.signal(signum, forward)
    libc = ctypes.CDLL(None, use_errno=True)
    relay = Relay(os.environ)
    # Relay 通道只留在本程序：pi 與工人的 bash 只看得到「有沒有通道」。
    env = {key: value for key, value in os.environ.items() if key not in CHANNEL}
    if relay.available:
        env["OSLAB_ASK_CHANNEL"] = "1"
    else:
        env.pop("OSLAB_ASK_CHANNEL", None)
    stream = Stream(relay)
    stream.send({"id": "prompt", "type": "prompt", "message": prompt})
    try:
        # close_fds=False：pi 照舊繼承呼叫端傳下來的描述符（Relay 的 worktree 鎖），跟 exec pi 時一樣；
        # 本程序自己開的描述符（含寫 pi stdin 的管線端）預設不可繼承，不會漏給 pi。
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, close_fds=False,
                                 env=env, preexec_fn=die_with_parent(libc, os.getpid()))
        pump(stream)
        code = child.wait()
    except Exception as exc:
        warn(f"crashed: {exc!r}")
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
        return 1
    return stream.finish(128 - code if code < 0 else code)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
