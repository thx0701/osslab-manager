# OSSLab Manager · Your strongest model as tech lead, a Flash model as the junior (Claude Code / Codex)

[中文](README.md) | **English**

What you want is a **senior tech lead running junior engineers**: the lead's judgment and stamina, at the junior's cost and speed.

This skill is that team. A strong model (Claude Opus 5.5+ / GPT-6 Astra) is the **tech lead**: it inventories the repo, splits the goal into tickets and defines acceptance — and, apart from small review fixes and wrapping up the last few small tickets, writes no implementation code, so nearly all of its quota goes into judgment. A cheap, fast Flash-tier model is the **junior engineer** who writes the code, and can ask the lead mid-task when it hits a scope or contract conflict. A model from another vendor reviews read-only; the lead verifies every finding, re-runs every acceptance command itself, and commits ticket by ticket.

**Senior judgment, junior cost** — however big the goal, what burns is DeepSeek Flash, not your Opus subscription.

## Support matrix

| Role | Supported | Notes |
|---|---|---|
| Tech lead (manager) | **Claude Code**, **Codex** | Only these two. Claude: Opus 5.5 or later, thinking high or above. Codex: GPT-6 Astra at a fixed **medium** (measured about 3× faster per step than xhigh) |
| Junior (default) | headless pi CLI + **DeepSeek v4.1 Flash** via **RunInfra** (pay per token; not OpenRouter and not DeepSeek's own API — see the note below) | `scripts/pi-runinfra-worker.sh` |
| Junior (same model, on request) | Same, via OpenRouter | Not an automatic fallback; only when the user asks: `scripts/pi-openrouter-worker.sh` |
| Junior (backup) | ZCode CLI + GLM-5.3-Flash (BigModel Coding Plan) | When DeepSeek fails acceptance for what looks like model capability: `scripts/zcode-cloud-worker.sh` |
| Junior (only when asked) | headless Claude Code + claude-haiku-5-5 (local subscription) | Manual dispatch only, not routed by Relay: `scripts/claude-haiku-worker.sh` |
| External review | In order: **Codex** GPT-6 Astra medium → **GLM-5.3** max → **Grok 4.7** medium (subscription ended); any can be requested | Read-only: Codex runs in its read-only sandbox, GLM and Grok get Read/Grep only; `scripts/codex-readonly-review.sh`, `scripts/zcode-readonly-review.sh`, `scripts/grok-readonly-review.sh` |

Cursor and ZCode do not act as tech lead: waiting, handoff and mid-task questions are verified only on Claude Code and Codex.

> **The DeepSeek provider matters**: we use [RunInfra](https://runinfra.ai)'s `deepseek-v4-1-flash` endpoint. RunInfra is hosting optimized for agent workloads: repeat calls from the same session go to the replica that already holds the cache (it claims 92–99%+ cache hits). In a single-round comparison on 2026-10-04 with the same model, it matched or slightly beat OpenRouter on time to the first tool call and was about 4–5× faster on long outputs, so it became the default; OpenRouter is kept as the fallback. Every speed and cost figure in this README comes from RunInfra — measure again before relying on them with OpenRouter or DeepSeek's own API.

## How it works

A goal → **inventory** (measure first, then ask; a gap table lets you pick the scope) → **decision readiness** (settled / observed / open; open questions come back to you) → **tickets** (one thing each, `blocked-by` dependencies, acceptance written as commands with expected output) → **dispatch** (clean environment, frozen helpers) → **lead acceptance** (a receipt is only the junior's claim; the lead re-runs the commands) → **out-of-family review** → **finding-by-finding verification** → **local commit per ticket** → batch code review before push → PR.

**Judgment lives in the skill, execution in a ledger.** Dispatch, waiting, recovery and handoff go to [Relay](https://github.com/thx0701/osslab-manager/tree/main/relay) (`osrelay`): a local CLI that records every ticket, attempt, question and evidence fingerprint in SQLite. Juniors outlive the lead's session; a new lead session takes over with `context`, not memory. `accept` checks in code that the latest run of every verification command passed on the current Git version, the review succeeded, and no evidence file was swapped; `finalize` checks that your commit is exactly the accepted tree.

New in this version:

- **Live progress**: every junior tool start/end, model reply and retry is written to the log as it happens (`bash: npm test`, `bash 完成 20.0s`). Relay's 900-second silence alarm now fires only when something is really stuck, and the last log line shows which command.
- **Ask the lead mid-task**: when a junior hits a scope or contract conflict ("the ticket only allows file A, but acceptance also needs B"), it calls `ask_manager` and pauses (four fixed fields: where it is stuck, options, recommendation, impact if unanswered; at most 3 per run). The lead's `osrelay wait` returns exit code 5 with the question; after `osrelay answer`, the junior continues in the same run. With no answer in 12 minutes it stops the affected part and records it in the receipt, as before. Answers count as ticket amendments in acceptance and review.

## Recent changes (2026-10)

- **Relay wakes the lead**: when an attempt ends or a junior asks, Relay steers one fixed-format notice through Paseo into the session the owner bound last (on by default for Codex, off for Claude; `bind --wake on|off`). A steer does not interrupt a running command and ends Codex's native `sleep` early. The notice carries only ids, statuses and deadlines, never junior-written text.
- **Codex leads sleep 5 minutes**: native `sleep` for 5 minutes, then one `osrelay wait --owner <owner> --timeout 0` covers every chain of the owner; a wake ends the sleep early, and the sleep still covers a broken wake. Polling with 1-second yields had made waiting 40–50% of the lead's tokens.
- **`osrelay wait --owner`**: one look at every attempt of an owner, reporting unreported ends, open questions, silence and wake failures; exit codes as for a single `wait`, plus `idle: true` when nothing is running.
- **Wrap-up mode**: with at most 3 small tickets left, or while the user is testing right after launch, the lead says "N left, I'll do them myself" and makes the changes; failing-first checks, re-run acceptance, external review and per-ticket commits still apply, and secrets, permissions, money and external contracts still go to a junior.
- **Review convergence and one acceptance entry**: from round 2, minor-only findings are fixed by the lead; a P1 still open after 3 fix rounds goes to a stronger worker or the lead, never Flash again. Multiple acceptance checks become one list run by the skill's `scripts/acceptance-run.sh`, i.e. a single verify; at most one acceptance-tool ticket per chain, later tool problems are fixed by the lead with code-review only.
- **Juniors follow YAGNI**: the worker prompt (`templates/worker-prompt.md`, shared by pi, ZCode and Haiku) asks for only what the ticket requires and the smallest, most direct solution (if one line does it, don't write ten), with no abstractions, options, compatibility layers or defensive code the ticket didn't ask for, but never at the cost of readability, error handling or acceptance. This applies to juniors only, not the lead.
- **pi juniors now run through an RPC driver**: `scripts/pi-worker-driver.py` starts pi with `pi --mode rpc`, replacing the `-p` text mode that printed nothing until the run ended. The driver writes live progress, relays questions, and decides success the way text mode did (pi itself still exits 0 on a model error; the driver turns that into exit 1). Signal forwarding, pi exiting when its parent dies, and Relay's worktree lock are unchanged.
- **`osrelay wait` exit codes**: 0 the query succeeded (check `result.status` for the outcome), 3 wait timeout (the work keeps running), 4 logs silent for 900 seconds, 5 a question is waiting. Both 4 and 5 are reported once: 4 once per set of log sizes, 5 once per question, except that a `wait` already running also reports questions asked after it began (even if a background wait reported them), so a lead blocked on a review still hears from other chains. 5 is reported before any other result.
- **Reading and answering**: `osrelay questions --owner <owner>` lists open questions in full; `osrelay answer <attempt> --qid <qid> --owner <owner> --text …` replies. Each question is reported once (except to a `wait` already running, see above), so a lead that chooses not to answer lets it expire after 12 minutes; a `wait` started later is not woken by it again.
- **Receipts gain "## 5. 問答" (Q&A)**: the junior lists each question, the lead's reply (or "no manager channel" / "no reply received"), and what it did. Answered questions go here, not in section 4 (risks and doubts), so they do not block the next `--resume`.
- **"無。" no longer blocks resume**: when Relay checks section 4 of a receipt for doubts, "無" ("none") with one list marker or a trailing full stop ("無。", "- 無") counts as no doubt; "無。但 X 未驗" ("none, but X unverified") or an extra bullet is still a doubt.
- **Acceptance must fail at the base commit**: a ticket that changes behavior needs at least one acceptance command that fails on the base commit, because of the behavior the ticket changes. The lead runs it before dispatch and records it in the ticket; a command that already passes at the base only guards against regressions. When only the junior's new tests can tell the difference, the lead re-checks during acceptance by running those tests against the base. This came from the benchmark, where one ticket's acceptance already passed at the base, so re-running it caught nothing.

## Quick start

1. Put this repo at `~/.agents/skills/osslab-manager/` (Codex scans it directly; Claude Code mounts the same copy through a symlink).
2. Create the secret files (keys travel only in environment variables, never argv/logs/git; change the paths at the top of `scripts/`):
   - `~/.openclaw/secrets/glm-5.3-flash.env`: `GLM_53_FLASH_API_KEY=...` (RunInfra, default junior)
   - `~/.openclaw/secrets/openrouter.env`: `OPENROUTER_API_KEY=...` (OpenRouter fallback)
   - `~/.openclaw/secrets/glm-coding-plan.env`: `ZHIPU_API_KEY=...` (GLM backup and GLM review)
3. Install `pi` (0.99 or later, RPC mode) and `python3`; `codex` (signed in with ChatGPT) for review, `grok` optional; `zcode` for the GLM backup and review (override its path with `ZCODE_CLI_BIN`).
4. Install Relay: `cd relay && python3 deploy/install-user.py`, then enable `osrelay.service` per [relay/docs/paseo.md](https://github.com/thx0701/osslab-manager/blob/main/relay/docs/paseo.md). Mid-task questions exist only under Relay; without it the lead dispatches by hand per `docs/manual-dispatch.md`, and a junior that asks gets "no manager channel" immediately.
5. In Claude Code or Codex, say "托管" / "走工單" / "派出去" (or ask it to use osslab-manager) and give a goal with the three essentials.

## The three essentials of a goal

1. **Boundary**: what is out of scope. A goal is a grant of authority; one without a boundary grants too much.
2. **Success signal**: what you will observe when it is done. This is the lead's acceptance anchor; you do not write the commands.
3. **Authoritative contract**: which spec or document is the source of truth. Settled decisions are reused, not re-asked.

Open business rules (money, permissions, penalties…) come back to you as one round of questions, each with a recommendation — that is not friction, it is the pipeline stopping "AI invents a business rule". One-page operator guide: [docs/operator-guide.md](docs/operator-guide.md).

## Field results

- **Speed and scale**: 167 pi junior runs through Relay between 2026-09-28 and 10-10 finished in a median 8 minutes, 90% within 25; one Codex (GPT-6 Astra) lead session dispatched 80 tickets over 14 hours.
- **Silence alarms became meaningful**: before live progress, that lead session received 20 silence alarms and all 20 tickets finished normally — every one a false alarm. Replaying pi session timestamps, the new version predicts 0 false alarms for that batch; across 43 long runs only 2 would fire, both real anomalies (a junior running `find /` or `grep -r` over the whole disk for 18 minutes).
- **Mid-task questions**: in a live smoke test the junior asked a contract-conflict question with evidence and three options; after the lead answered, it received the answer within 15 seconds, finished, and recorded the exchange in its receipt.
- **More accurate than solo development**: every ticket passes three independent checks — re-run acceptance, out-of-family review, finding-by-finding verification. A model reviewing its own work shares its own blind spots.
- **The only cost is time**: a mid-sized ticket takes about 1.5 hours from dispatch to the end of three review rounds; not for emergencies.
- **Worker benchmark (2026-10-11)**: DeepSeek on RunInfra vs Claude Haiku 5.5 on three real tickets, three rounds: DeepSeek succeeded 9/9 and was 1.5–1.7× faster; Haiku on a Pro subscription used about 1–2% of the 5-hour window per ticket. Full report: [docs/benchmarks/2026-10-11-deepseek-vs-haiku.en.md](docs/benchmarks/2026-10-11-deepseek-vs-haiku.en.md).

### Case: browser-workflow (browser leasing with human takeover)

28 files, +5,091 lines; 4 tickets (T1 plus 3 fix tickets), 3 Grok review rounds, about 1.5 hours, ending with 60 passing tests in one commit. The junior's own 57 tests were all green, yet round one found 8 valid issues (lease renewal could hang; grandchildren survived the parent); round two caught a bypassable production wrapper and a read/write format mismatch that corrupted state on restart; round three was clean. All of these are "tests green, behavior wrong" defects.

## Three-stage sessions

The lead switches sessions by responsibility: **spec** (align, inventory, split tickets, post the checklist) → **build** (dispatch juniors, collect receipts, answer questions) → **acceptance** (re-run acceptance, review, verify, commit). Each stage ends with a ~2KB handoff in `~/.local/state/osslab-manager/handoffs/`, and the next stage starts from that alone; a stage also switches after about 3 hours or ~60% context. Details in SKILL.md section 9.

### Optional: automatic stage handoff with Paseo

Everything works without [Paseo](https://github.com/getpaseo/paseo); Relay does not depend on it. With it, when you set a persistent goal (goal, Codex `/goal`), the lead opens the next stage itself with Paseo's `create_agent` at the end of each stage; our environment uses it for stage handoffs.

## When not to use it

- One-line fixes or copy edits — just do them; don't pay the ticket overhead.
- Exploratory spikes: if you cannot say what "done" looks like, you cannot write acceptance.
- Decision-dense work: if every ticket needs a human call, the lead is just a relay — settle it first.

## Safety boundaries

- Juniors start in a **clean environment** without the lead session's tokens or business credentials; pi juniors also start lean — no skills, no other extensions, no AGENTS.md at any level — and are told to read the repo's own rules.
- Answers to mid-task questions reach the junior only through pi's RPC stdin; the write end is never inherited and Relay's channel variables never reach pi, so a junior cannot answer itself. Irreversible actions, production and secrets may not be asked about, and stay forbidden even if the lead answers.
- Reviewers are **read-only** (Read/Grep) and may not edit files.
- Implementation goes only through the helper CLIs; host subagents (Claude Agent/Task, Codex subagents) are banned — they run inside the lead's process and bypass the whole isolation design.
- Isolation is an operating contract under one OS user, not a permission sandbox: juniors still run a local shell. Tickets carry no secrets, and production checks are done by the lead.

## Differences from upstream (yanauto/opus-manager)

- Pre-set worker routing: DeepSeek (RunInfra) default, GLM-5.3-Flash backup whenever it cannot be used (OpenRouter only on request), read-only review in the order Codex → GLM → Grok; Claude Haiku only by explicit manual dispatch
- Relay ledger: dispatch, waiting, recovery, handoff, acceptance and commit checks with programmatic evidence fingerprints
- Live progress and mid-task questions (pi RPC driver + `ask_manager` extension)
- Measure first, then ask: inventory produces a gap table; humans own scope, the lead owns granularity
- `blocked-by` dependencies; independent chains run in parallel on separate worktrees
- Review tiers (`review-tier`): anything touching assertions, guards, money or permissions is high tier; tiers only go up
- Lead hotfix: verified non-blocking nits may be fixed directly; blocking findings still go to a junior (except in wrap-up mode)
- Wrap-up mode: up to 3 small tickets left or post-launch tuning, the lead does them itself with the same gates
- Relay wake: a Paseo steer wakes the lead when an attempt ends or a junior asks; Codex sleeps 5 minutes as the fallback
- Dead-ticket recovery: PID-reuse checks, partial changes backed up first, re-dispatch recorded on the same ticket
- Three-stage sessions with 2KB handoffs
- All timestamps in Taiwan time (UTC+8), our team's rule — see Environment if you are in another time zone

## Environment

Relay needs Linux, Python 3.11+ and Git, standard library only; run the runner as a systemd user service. The `develop → implement → verify-change → code-review` and `to-tickets` chain mentioned in SKILL.md is our internal companion skill set; substitute your own development flow. Change key paths and model routing at the top of `scripts/`.

**Time zone**: every timestamp is hardcoded to Taiwan time (UTC+8), our team's rule. Helper start lines, Relay records, evidence files and receipts carry the `+08:00` offset, so the instants are correct; the live-progress lines in worker logs show only `HH:MM:SS` without an offset. If you are not in UTC+8, change these yourself for now: `TZ=Asia/Taipei` in `scripts/*.sh`, `timedelta(hours=8)` in `scripts/pi-worker-driver.py` and `scripts/evidence-run.sh`, `Asia/Taipei` in `scripts/zcode-review.py`, `now()` in `relay/osrelay/artifacts.py`, and the completion-time instruction in `templates/worker-prompt.md` and `templates/receipt.md`.

## Roadmap

- Configurable time zone (currently fixed to UTC+8).
- Follow-up comparison (continuing the [worker benchmark](docs/benchmarks/2026-10-11-deepseek-vs-haiku.en.md); list agreed after a GLM-5.3 High cross-review):
  - **End-to-end cost and time**: A (Opus lead + DeepSeek) and B (Opus lead + Haiku) including the lead's time, tokens and subscription usage for writing tickets, waiting, re-running acceptance and external review; C (Opus 5.5 writing it itself) at effort low and medium; D (Haiku with an Opus advisor via Claude Code `--advisor`, after confirming it works on a subscription), recording how often it actually consults.
  - **Quality**: compare against the final tests that were accepted at the time, after dropping acceptance commands that already pass at the base.
  - **Sampling bias and tail latency**: add tickets DeepSeek did not finish in one pass; record the slowest runs (p95) for each setup, not just the median.

## License

MIT, see [LICENSE](LICENSE). Adapted from [yanauto/opus-manager](https://github.com/yanauto/opus-manager) (MIT).
