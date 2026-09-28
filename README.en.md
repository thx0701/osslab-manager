# OSSLab Manager · Strong model as tech lead, flash models as juniors (works with Claude / ZCode / Codex / Cursor)

[中文](README.md) | **English**

What you want is a team of a **senior tech lead managing junior engineers**: the lead's judgment and stamina, with the juniors' cost and speed.

This skill is that team. A strong model (Opus 5.5+ / GPT-6 Astra) is the **tech lead**: it takes stock of the repo, splits the work into tickets, and defines acceptance. It writes no implementation code, so all of its budget goes into judgment. Cheap, fast flash-tier models are the **junior engineers** who write the code. A model from another vendor does a read-only external code review; the tech lead checks each finding, re-runs every acceptance command itself, and commits ticket by ticket.

**Senior judgment, junior cost.** However big the goal, the tokens spent on implementation are DeepSeek Flash tokens, not your Opus subscription.

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
4. In chat, say 托管 / 走工單 / 派出去 (delegate / run tickets / dispatch) or `osslab-manager`, give a goal with the three things above, and the tech lead follows the skill.

## Flow

A goal (three things) → stocktake (measure before asking; a gap table lets you choose scope) → decision readiness (settled / observed / undecided; undecided goes back to you) → ticketing (one thing per ticket, full `blocked-by` dependencies, acceptance written as commands with expected output, a predicted `review-tier`) → dispatch (clean environment, optional frozen helpers, a recovery procedure for dead tickets) → tech lead acceptance (a receipt is only the junior's claim; the lead re-runs the commands) → out-of-family review (Grok for high-tier tickets, skipped for low-tier) → finding-by-finding verification (reviewers are often wrong) → local commit per ticket (blocking findings can't be deferred to another ticket; verified small nits may be fixed by the lead directly) → a batch code review before push → PR.

Tickets live in `_tickets/open|doing|done/` (the directory is the status), receipts in `_receipts/`, run records in `~/.local/state/osslab-manager/`.

## Long sessions

The tech lead doesn't switch sessions after every section. It switches only when the PR is merged, you stop it, it is waiting on your decision, or the session has run for about 3 hours (or context passes about 60%, when the runtime reports usage). Then it writes a handoff of about 2KB under `~/.local/state/osslab-manager/handoffs/` and moves to a new session, which only checks HEAD and the next ticket instead of redoing the stocktake. On Paseo, if you already set a goal (or Codex `/goal`), the lead opens the next session itself; otherwise it stops and gives you a prompt to paste. The procedure is in SKILL.md, section 九.

While a worker runs, the lead waits once until it finishes instead of polling every few seconds. A Codex tech lead always runs at medium effort.

Team-facing timestamps use Taiwan time (+0800); the host clock runs UTC, so helpers already set `TZ=Asia/Taipei` for stamps. Grok stays the default read-only reviewer.

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

The `develop → implement → verify-change → code-review` chain mentioned in SKILL.md is our internal set of companion skills; external users can swap in their own development flow, and the same goes for alignment tools such as grill / to-spec. Key paths and model routing are set in the first few lines of each script under `scripts/`.

## License

MIT, see [LICENSE](LICENSE). Adapted from [yanauto/opus-manager](https://github.com/yanauto/opus-manager) (MIT).
