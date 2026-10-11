# Worker benchmark: DeepSeek v4.1 Flash (RunInfra) vs Claude Haiku 5.5 (2026-10-11)

[中文](2026-10-11-deepseek-vs-haiku.md) | **English**

## Summary

- **DeepSeek v4.1 Flash on RunInfra stays the default junior**: 9 of 9 runs succeeded across three real tickets and three rounds; it was 1.5–1.7× faster than Haiku and, at official API prices, cheaper in most cases.
- **Claude Haiku 5.5 is dispatched only on request**: on a Claude Pro subscription each ticket used about 1–2% of the 5-hour window — far cheaper than having Opus 5.5 write the code itself — but it is slower than DeepSeek, its run time varies widely, and it shares the subscription window with the Claude lead.
- A Haiku helper start-up misjudgement found during the benchmark has been fixed and deployed (see "Problems found").

## Where the DeepSeek numbers come from: RunInfra, not OpenRouter or DeepSeek's own API

**Every DeepSeek figure in this report comes from RunInfra's** ([runinfra.ai](https://runinfra.ai)) `deepseek-v4-1-flash` endpoint. With another provider the speed and cost conclusions may not hold.

- **What it is**: RunInfra describes itself as hosted model APIs optimized for agent workloads, built around session-aware routing — repeat calls from the same agent session go to the replica that already holds that context. It claims 92–99%+ cache hits and about 378 output tokens per second for DeepSeek V4.1 Flash (website, 2026-10-11).
- **Why we use it**: in a single-round comparison on 2026-10-04 with the same `deepseek-v4-1-flash`, RunInfra matched or slightly beat OpenRouter on time to the first tool call and was **about 4–5× faster on long outputs**, so it became the default junior. OpenRouter is kept as the fallback (`scripts/pi-openrouter-worker.sh`).
- **The caching is visible in our data**: in round 1 of t5a, DeepSeek read about 3.85M input tokens, about 96% of them from cache.
- **Prices**: costs use RunInfra list prices — $0.14 input, $0.03 cached input, $0.58 output per million tokens (`scripts/runinfra-agent/models.json`). The website showed 25% off on 2026-10-11, so actual bills are lower.

## Method

- **Tickets**: three real tickets from Relay history that DeepSeek originally finished in one pass — t5a (Python, a date bug in test fixtures), t4d (Python, configuration and secret handling), t1 (Go, call-route guarding and SMS queries).
- **Fairness**: each worker got its own worktree from the same base commit and the same ticket text (only the original worktree path was replaced), and both ran at the same time. Both were dispatched by hand, so neither had the mid-task question channel. Three rounds.
- **Worker settings**: DeepSeek = pi (RPC driver, thinking high); Haiku = headless Claude Code 2.1.286, effort high, Claude Pro subscription.
- **Acceptance**: the verification commands Relay recorded for each ticket, re-run after every worker.

## Results

### Reliability

| Worker | Succeeded |
|---|---|
| DeepSeek (RunInfra) | 9 / 9 |
| Haiku (before the fix) | 4 / 7 (3 false rejections by the helper) |
| Haiku (after the fix) | 3 / 3, plus 4 / 4 direct calls through the real Claude CLI |

### Speed (successful runs only)

| Ticket | DeepSeek, 3 rounds | Haiku, successful rounds | Median ratio |
|---|---|---|---|
| t5a (Python) | 286 / 341 / 317 s | 488 / 420 / 1,475 s | Haiku 1.5× slower |
| t4d (Python) | 100 / 147 / 113 s | 183 / 205 s | Haiku 1.7× slower |
| t1 (Go) | 244 / 286 / 367 s | 416 / 419 s | Haiku 1.5× slower |

DeepSeek itself varied 20–45% between rounds. Haiku's 1,475 s on t5a round 3 was real work: it ran tests as background tasks (7 of them), and each completion made Claude Code start a new turn until the job ended.

### Cost per ticket (USD)

| Ticket | DeepSeek (RunInfra list price) | Haiku (at official API price) | Same tokens at Opus 5.5 prices |
|---|---|---|---|
| t5a | 0.13–0.16 | 0.32–0.39 | 3.3–3.6 |
| t4d | 0.04–0.05 | 0.04–0.05 | 1.5–1.8 |
| t1 | 0.11–0.17 | 0.32–0.35 | 3.3 |

- On the larger tickets Haiku cost about 2.5× more: it produced about twice DeepSeek's output, roughly two thirds of it thinking tokens, and once a single prompt passed 100K tokens the higher price tier applied (25 of 47 calls in t5a round 1).
- Haiku actually ran on the Pro subscription and was not billed per token; the table shows what it would cost through the API.
- "Same tokens at Opus 5.5 prices" is only a rough reference — Opus writing the code itself would take different turns and behave differently. It was not measured.

### Subscription usage (Haiku)

Each ticket used about 1–2% of the Claude Pro 5-hour window (t5a round 3 ran 25 minutes and moved it from 5% to 7%). The window is shared with Claude.ai and every other Claude Code session on the account, including a Claude lead.

### Quality

Every successful run passed its verification commands. **That is not enough to compare quality**: t1's commands already pass on the base commit, and the check against the final accepted tests did not complete. This report does not judge which worker did better.

## Problems found and fixed

- **Haiku helper start-up misjudgement (fixed in osslab-manager PR #627)**: Claude Code 2.1.286 sometimes emits `system/ui_invalidate` before `system/init`. `scripts/claude-haiku-run.py` only looked at the first line and rejected a healthy start as `model=missing`. It now holds up to 20 system events before `init`, writes them out once `init` passes the model and auth checks, and still rejects any other event, non-JSON output, or too many events before `init`. Failures happened at 2–74% subscription usage with status `allowed`; quota was not the cause.
- **The Claude CLI's Haiku cost figure is wrong**: CLI 2.1.286 does not recognize `claude-haiku-5-5` (`unrecognized_model`, `costBasis: unknown`) and prices `total_cost_usd` at Opus 5.5 rates, about 10–35× Haiku's real price. Compute cost from token counts and official prices.
- **A timing bug in this benchmark's own script (fixed)**: the first two rounds waited for DeepSeek before collecting Haiku, so whichever finished first was recorded with the other's time. It only affected the 3 failed Haiku runs (each actually exited within 2 seconds); successful runs match Claude's own `duration_ms` within 2 seconds.

## Limitations

- Small sample: three tickets, three rounds, all small to medium (2–6 minutes for DeepSeek).
- Quality was not compared (see above).
- "Opus 5.5 writes it itself" was not measured.
- Haiku's subscription usage is affected by other sessions on the same account.
- DeepSeek was measured only on RunInfra; OpenRouter and DeepSeek's own API were not part of this run.

## Current routing

DeepSeek on RunInfra is the default junior; if RunInfra is paused or rate/quota limited, the same model via OpenRouter; if the model lacks capability, the GLM backup. Claude Haiku is dispatched by hand only when the user asks, and is not routed by Relay.
