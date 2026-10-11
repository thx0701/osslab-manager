# Worker benchmark: DeepSeek v4.1 Flash (RunInfra) vs Claude Haiku 5.5 (2026-10-11)

[中文](2026-10-11-deepseek-vs-haiku.md) | **English**

## Summary

- **DeepSeek v4.1 Flash on RunInfra stays the default junior**: 9 of 9 runs succeeded across three real tickets and three rounds; it was 1.5–1.7× faster than Haiku and, at official API prices, cheaper in most cases.
- **Claude Haiku 5.5 is dispatched only on request**: on a Claude Pro subscription each ticket used about 1–2% of the 5-hour window — far cheaper than having Opus 5.5 write the code itself — but it is slower than DeepSeek, its run time varies widely, and it shares the subscription window with the Claude lead.

## Where the DeepSeek numbers come from

The DeepSeek in this report runs on [RunInfra](https://runinfra.ai): hosting optimized for agent workloads, where calls from the same session hit a warm cache (92–97% of DeepSeek's input across the nine runs came from cache). In an earlier test of the same model, RunInfra was about 4–5× faster than OpenRouter on long outputs. With OpenRouter or DeepSeek's own API, measure the speed and cost again. Costs use RunInfra list prices: $0.14 input, $0.03 cached input, $0.58 output per million tokens.

## Method

- **Tickets**: three real tickets from Relay history that DeepSeek originally finished in one pass — t5a (Python, a date bug in test fixtures), t4d (Python, configuration and secret handling), t1 (Go, call-route guarding and SMS queries).
- **Fairness**: each worker got its own worktree from the same base commit and the same ticket text (only the original worktree path was replaced), and both ran at the same time. Both were dispatched by hand, so neither had the mid-task question channel. Three rounds.
- **Worker settings**: DeepSeek = pi (RPC driver, thinking high); Haiku = headless Claude Code 2.1.286, effort high, Claude Pro subscription.
- **Acceptance**: the verification commands Relay recorded for each ticket, re-run after every worker.

## Results

### Reliability

Every run that actually worked on a ticket succeeded and passed its verification commands: 9 for DeepSeek, 7 for Haiku.

### Speed

| Ticket | DeepSeek, 3 rounds | Haiku, each round | Median ratio |
|---|---|---|---|
| t5a (Python) | 286 / 341 / 317 s | 488 / 420 / 1,475 s | Haiku 1.5× slower |
| t4d (Python) | 100 / 147 / 113 s | 183 / 205 s | Haiku 1.7× slower |
| t1 (Go) | 244 / 286 / 367 s | 416 / 419 s | Haiku 1.5× slower |

DeepSeek's own slowest round took 19–51% longer than its fastest. Haiku's 1,475 s on t5a round 3 was real work: it ran tests as background tasks (7 of them), and each completion made Claude Code start a new turn until the job ended.

### Cost per ticket (USD)

| Ticket | DeepSeek (RunInfra list price) | Haiku (at official API price) | Same tokens at Opus 5.5 prices |
|---|---|---|---|
| t5a | 0.13–0.16 | 0.32–0.39 | 3.3–3.6 |
| t4d | 0.04–0.05 | 0.04–0.05 | 1.5–1.8 |
| t1 | 0.11–0.17 | 0.32–0.35 | 3.3 |

- On the larger tickets Haiku cost about 2.5× more: it produced about twice DeepSeek's output, roughly two thirds of it thinking tokens, and once a single prompt passed 100K tokens the higher price tier applied (25 of 47 calls in t5a round 1).
- Haiku actually ran on the Pro subscription and was not billed per token; the table shows what it would cost through the API, from token counts at official prices.
- "Same tokens at Opus 5.5 prices" is only a rough reference — Opus writing the code itself would take different turns and behave differently. It was not measured, and it likely overstates the cost: Anthropic measured Opus 5.5 at about $0.12 (low) to $0.29 (high) per solved SWE-bench Pro task ([source](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), API list prices; different tasks and harness from this test).
- Claude Code writes 1-hour cache entries, so both the Haiku and Opus columns use 1-hour cache-write prices (per million tokens: Haiku 5.5 $0.20, or the higher tier once a prompt passes 100K; Opus 5.5 $8).

### Three setups, all three tickets (to be completed)

| Setup | Total time, three tickets | Total cost, three tickets (USD) |
|---|---|---|
| A. Opus lead + DeepSeek junior | Junior 10.5–13.3 min (three rounds) | Junior 0.30–0.36 (RunInfra list price) |
| B. Opus lead + Haiku junior | Junior 18.1–35.0 min (rounds 1 and 3) | Junior 0.75–0.77 at API prices; actually ran on Pro |
| C. Opus 5.5 writes it itself | Not measured | Not measured |

This table is incomplete: A and B count only the junior — the lead's (Opus) time and tokens for writing tickets, waiting and reviewing were not measured — and C was not run. **A follow-up test will fill it in**: the same three tickets, A and B including the lead's time and cost, C as headless Opus 5.5 doing the work directly, with total time, total cost and subscription usage side by side. The full follow-up list is in the [README roadmap](../../README.en.md#roadmap).

### Subscription usage (Haiku)

Each ticket used about 1–2% of the Claude Pro 5-hour window (t5a round 3 ran 25 minutes and moved it from 5% to 7%). The window is shared with Claude.ai and every other Claude Code session on the account, including a Claude lead.

### Quality

Every run passed its verification commands. **That is not enough to compare quality**: t1's commands already pass on the base commit, and the check against the final accepted tests did not complete. This report does not judge which worker did better. osslab-manager now requires at least one acceptance command that fails at the base commit for any ticket that changes behavior.

## Limitations

- Small sample: three tickets, three rounds, all small to medium (2–6 minutes for DeepSeek), and all tickets DeepSeek originally finished in one pass, which favours it.
- Quality was not compared (see above).
- "Opus 5.5 writes it itself" was not measured, and the lead's cost was not counted; both come in the follow-up test (see "Three setups").
- Haiku's subscription usage is affected by other sessions on the same account.
- DeepSeek was measured only on RunInfra; OpenRouter and DeepSeek's own API were not part of this run.

## Current routing

DeepSeek on RunInfra is the default junior; if RunInfra is paused or rate/quota limited, the same model via OpenRouter; if the model lacks capability, the GLM backup. Claude Haiku is dispatched by hand only when the user asks, and is not routed by Relay.
