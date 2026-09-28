# OSSLab Manager · Strong model as tech lead, flash models as juniors (works with Claude / ZCode / Codex / Cursor)

[中文](README.md) | **English**

What you want is a team of a **senior tech lead managing junior engineers**: the lead's judgment and stamina, with the juniors' cost and speed.

This skill is that team. A strong model (Opus 5.5+ / GPT-6 Astra) is the **tech lead**: it takes stock of the repo, splits the work into tickets, and defines acceptance. It writes no implementation code, so all of its budget goes into judgment. Cheap, fast flash-tier models are the **junior engineers** who write the code. A model from another vendor does a read-only external code review; the tech lead checks each finding, re-runs every acceptance command itself, and commits ticket by ticket.

**Senior judgment, junior cost.** However big the goal, the tokens spent on implementation are DeepSeek Flash tokens, not your Opus subscription.

## Why this version: pin the goal down, then break it up

The first version's problem was not a weak model. It was **one session carrying every responsibility**: aligning requirements, taking stock, dispatching, waiting, accepting, reviewing, and committing all lived in one context. Judgment got muddier toward the end, and when the session dropped, the dispatched workers and the acceptance progress dropped with it.

This version borrows two ideas from [OpenRig](https://github.com/mvschwarz/openrig) — **durable roles** and **explicit handoffs** — and splits the work into two layers:

1. **Settle the goal before splitting it.** The spec segment does one thing: agree with you on what to do, what not to do, and what counts as done, written as a confirmation checklist. If "what not to do" can't be written, the scope isn't settled and nothing is dispatched. Only then is the goal split into tickets and ticket chains (one chain shares one git worktree; only independent chains run in parallel).
2. **Judgment stays in the skill; execution goes to a ledger.** The tech lead only judges (splitting, acceptance, verifying findings, committing). Dispatch, waiting, recovery, and handoff go to [Relay](https://github.com/thx0701/osslab-manager/tree/main/relay) (`osrelay`), a local CLI that records every ticket, attempt, and evidence fingerprint in SQLite. Workers outlive the tech lead; a new session picks up with `context` instead of memory. `accept` checks in code that the latest run of every command verified on the ticket succeeded, the latest review succeeded (or a low-tier waiver was given with a reason), and all of it matches the current Git version with untampered evidence — it does not judge whether the commands were the right ones. `finalize` checks that your commit is exactly the accepted tree, is HEAD, leaves a clean worktree and index, and is a single-parent child of the accepted base (with no change, the original HEAD may close it).

So sessions are split by responsibility — **spec → build → acceptance** — and each segment ends with a ~2KB handoff that the next one starts from (see "Three-segment sessions" below).

### Do you need Paseo?

**No, but it's recommended.** Three layers:

- **Skill**: works on any host; without Relay the tech lead dispatches with the helpers in `scripts/`.
- **Relay**: on any Linux host with `osrelay` installed, a Claude Code or Codex tech lead goes through Relay (in Paseo or a plain terminal). ZCode / Cursor can dispatch too, but `bind` only records codex / claude.
- **Paseo**: adds one thing — automatic segment hand-over.

What [Paseo](https://github.com/getpaseo/paseo) adds is **automatic segment hand-over**: when you have set a persistent goal (a goal, "run it to the end", Codex `/goal`), the tech lead ends a segment by opening the next session itself through Paseo's `create_agent`. Without Paseo it stops and gives you an opening prompt to paste into a new session. Long ticket chains that span several segments save the most hands with Paseo.

## Three things to give with a goal

The goal stops at the tech lead; below it, every ticket is a contract with acceptance commands and expected output. For the tech lead to take the goal on, state three things:

1. **Boundary**: what is out of scope. The goal is the authorization scope; a goal without boundaries authorizes too much.
2. **Success signal**: what you will observe when it's done. This is the tech lead's acceptance anchor; you don't write the commands yourself.
3. **Authoritative contract**: which spec or document is the source of truth for decisions. Settled decisions are reused, not asked again.

Example: "Bring the FB Marketplace listing flow up to full spec coverage. Payments and shipping are out of scope. When done, every item shows its matching specs and status in the shop. Source of truth: `docs/listing-spec.md`."

For undecided business rules (money, permissions, penalty terms…) the tech lead comes back and asks you, one question at a time. That isn't friction: it's the pipeline stopping the AI from inventing business rules.

## What we've seen in practice

- **The cost structure flips**: implementation runs on pay-per-token flash-tier juniors (same-ticket comparison: DeepSeek Flash was about 7× faster than GLM-5.3-Flash on small tickets). The tech lead's budget goes only to stocktaking, splitting, acceptance, and verification. Multiple tickets can run in parallel in separate worktrees.
- **More accurate than a single agent**: every ticket passes three independent checks: acceptance commands re-run by the tech lead, out-of-family review, and finding-by-finding verification. A single agent reviews its own work with the same blind spots. The pipeline also forces "what counts as done" to be written as commands, which removes a whole class of ambiguity.
- **The only cost is time**: a medium ticket takes about 1.5 hours from dispatch to the end of three review rounds, so it's not for urgent work. Everything else is cheap. Well worth it.

### Case study: browser-workflow (browser leasing and manual takeover)

28 files, +5,091 lines; 4 tickets (T1 plus 3 fix tickets) and 3 Grok review rounds in about 1.5 hours. It ended with 60 passing tests, squashed into one commit.

- The junior's own 57 tests were all green, yet the first review found 8 valid issues. The tech lead also wrote repro scripts and caught a hanging lease renewal and grandchild processes left behind after the parent exited.
- The second round caught 2 more blocking issues: the production wrapper could be bypassed without sending a signal, and the write and read formats disagreed, corrupting state on restart. Before the fix all 3 invalid inputs were accepted and restart returned `corrupt_state`; after the fix all were rejected and restart was clean.
- Only after a clean third round was it committed.

These are "tests green but actually wrong" defects, the kind a model reviewing its own code rarely catches.

## Recommended setup (harness and models)

| Role | Recommendation | Notes |
|---|---|---|
| Tech lead harness | Any of Claude Code / Codex / ZCode / Cursor | All four runtimes share the same skill |
| Tech lead model (subscription) | Claude **Opus 5.5 or later** (reasoning **high or above**), or **GPT-6 Astra** (always **medium**: measured about 3× faster per step than xhigh) | The lead's value is all judgment (splitting, acceptance, verification); don't skimp here |
| Junior engineer | **DeepSeek 4.1 Flash** (pi headless, pay per token) | Cheap and fast; this is the one |
| External review | **Grok** or **GLM** both work | Review quality is similar; pick one from a different vendor than the lead and the juniors |

## Three roles

(Inside SKILL.md the tech lead is called 經理 "manager" and the junior 工人 "worker": same roles, plainer words here.)

| Role | Runs as | Invocation |
|---|---|---|
| Tech lead | Claude Code / ZCode / Codex (GPT-6 Astra) / Cursor with this skill loaded | — |
| Junior (default) | pi CLI in headless mode; `deepseek/deepseek-v4.1-flash` via OpenRouter (pay per token) | `scripts/pi-openrouter-worker.sh <workdir> <ticket>` |
| Junior (fallback) | ZCode CLI in headless mode; `GLM-5.3-Flash` (BigModel Coding Plan) | `scripts/zcode-cloud-worker.sh <workdir> <ticket>` |
| External review | Grok Build `grok-4.7` (medium), read-only Read / Grep; GLM also possible | `scripts/grok-readonly-review.sh <workdir> <prompt-file>` |

## Quick start

1. Put this repo in your agent skill directory (for example `~/.agents/skills/osslab-manager/`; each runtime's view mounts the same source).
2. Prepare two secret files (keys never go into argv, logs, or git):
   - `~/.openclaw/secrets/openrouter.env`: `OPENROUTER_API_KEY=...`
   - `~/.openclaw/secrets/glm-coding-plan.env`: `ZHIPU_API_KEY=...`
   - Override the ZCode CLI location with `ZCODE_CLI_BIN`.
3. Install the `pi` and `zcode` CLIs locally; reviews use `grok` (or a GLM-style read-only reviewer).
4. (Recommended) Install Relay: `cd relay && python3 deploy/install-user.py`, then enable `osrelay.service` as described in [relay/docs/paseo.md](https://github.com/thx0701/osslab-manager/blob/main/relay/docs/paseo.md). The tech lead then dispatches through Relay per [docs/relay.md](docs/relay.md).
5. In chat, say 托管 / 走工單 / 派出去 (delegate / run tickets / dispatch) or `osslab-manager`, give a goal with the three things above, and the tech lead follows the skill.

## Flow

A goal (three things) → stocktake (measure before asking; a gap table lets you choose scope) → decision readiness (settled / observed / undecided; undecided goes back to you) → ticketing (one thing per ticket, full `blocked-by` dependencies, acceptance written as commands with expected output, a predicted `review-tier`) → dispatch (clean environment, optional frozen helpers, a recovery procedure for dead tickets) → tech lead acceptance (a receipt is only the junior's claim; the lead re-runs the commands) → out-of-family review (Grok for high-tier tickets, skipped for low-tier) → finding-by-finding verification (reviewers are often wrong) → local commit per ticket (blocking findings can't be deferred to another ticket; verified small nits may be fixed by the lead directly) → a batch code review before push → PR.

Tickets live in `_tickets/open|doing|done/` (the directory is the status), receipts in `_receipts/`, run records in `~/.local/state/osslab-manager/`.

## Three-segment sessions

The tech lead splits work by responsibility instead of cramming it into one session: a **spec segment** (align, take stock, split tickets, post the confirmation checklist), a **build segment** (dispatch juniors, collect receipts), and an **acceptance segment** (re-run acceptance, review, verify findings, commit). Each segment ends with a handoff of about 2KB under `~/.local/state/osslab-manager/handoffs/`, and the next segment starts from that file alone. Low-tier tickets may be accepted in the build session, and fix-up tickets stay in the acceptance segment; a segment that has run about 3 hours (or passes about 60% context, when reported) also switches. On Paseo, if you already set a goal (or Codex `/goal`), the lead opens the next segment itself; otherwise it stops and gives you a prompt to paste. See SKILL.md section 九. An operator one-pager (in Chinese) is at [docs/operator-guide.md](docs/operator-guide.md).

## When not to use it

- One-line fixes or copy changes: just do them; don't pay the ticketing overhead (the skill itself says so: work normally unless asked to delegate).
- Exploratory spikes: if you can't yet say what "done" looks like, you can't write acceptance.
- Decision-heavy work: if every ticket needs a human call, the tech lead is just a relay. Settle the decisions first, then enter the pipeline.

## Safety boundaries

- Juniors start in a **clean environment** (they don't inherit the tech lead session's tokens or business credentials); keys travel only in environment variables, never argv, logs, or git. The pi junior also starts minimal: no skills or extensions, and no AGENTS.md is auto-loaded at any level; its instructions tell it to read the repo's own rules.
- The reviewer is **read-only** (Read / Grep, MCP tools denied) and may not edit files.
- Implementation goes only through the helper CLIs; host subagents (Claude Task / Codex subagents / Cursor Task) are banned, because they run inside the tech lead's process and bypass the whole isolation design.

## Differences from upstream (yanauto/opus-manager)

- Worker routing is preset (no per-task discovery): DeepSeek by default, GLM as fallback, Grok for read-only review
- Works across four runtimes: all dispatch in the background; Claude Code and ZCode wait for completion notices, Codex uses managed sessions with a code-mode loop, Cursor waits in the foreground with `wait-worker.sh`
- Measure before asking: stocktaking produces a gap table and a human picks the scope; in ticketing, humans own scope and the tech lead owns granularity
- Tickets have a `blocked-by` dependency field; only unblocked tickets are dispatched; separate worktrees run separate chains in parallel
- Review tiers (`review-tier`): anything touching assertions / guards / money or permissions is high tier; tiers only go up, never down
- Tech lead direct fixes: verified, non-blocking small nits may be fixed directly (≤10 lines, no behavior change); copy that only restates existing behavior (README, verification reports) may be edited directly up to about 20 lines, but never receipts or specs; all valid findings from one review round go into a single fix ticket instead of one ticket per finding (blocking findings still go to a junior)
- Recovery for tickets stuck in `doing`: PID-reuse check, half-finished changes saved as a patch, re-dispatches recorded on the same ticket
- Commit gate: each ticket must pass acceptance, verification, and review verification before commit; valid blocking findings can't be deferred to another ticket
- Helpers keep keys out of argv, start workers in a clean environment, and connect stdin to /dev/null
- Team timestamps use Taiwan time (+0800)

## Environment assumptions

Relay (`relay/`) needs Linux, Python 3.11+, and Git, and uses only the standard library; run its runner as a systemd user service. The `develop → implement → verify-change → code-review` chain and `to-tickets` mentioned in SKILL.md are our internal set of companion skills; external users can swap in their own development flow, and the same goes for alignment tools such as grill / to-spec. Key paths and model routing are set in the first few lines of each script under `scripts/`.

## License

MIT, see [LICENSE](LICENSE). Adapted from [yanauto/opus-manager](https://github.com/yanauto/opus-manager) (MIT).
