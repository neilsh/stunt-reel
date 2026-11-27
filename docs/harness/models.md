# Models and the routing labels

Which model of each harness fits each `model-tier:` label, and which count as `model-context:wide`.
The labels and their meaning are in [`triage-labels.md`](../agents/triage-labels.md#model-roles), and the routing policy (what a label sends to which harness) is the table in [`harness.md`](../harness.md#policy-any-agent).
This page only says which vendor models fit each label, so a model change edits this page and not the labels.

Dated 2026-11-27; vendors change lineups every few months, so refresh it when a harness adds or retires a model, and at least quarterly.
Map by where a vendor positions a model and by its context window, never by a model name's version number.

## Tiers

### Claude Code

Checked against Anthropic's [models overview](https://platform.claude.com/docs/en/about-claude/models/overview), 2026-11-27.

| Label | Model | Notes |
| --- | --- | --- |
| `model-tier:light` | `Haiku` | Positioned for high-volume, latency-sensitive work |
| `model-tier:medium` | `Sonnet` | The default implementer; `Haiku` goes first on a `medium` issue whose plan names the files, change and test ([`harness.md`](../harness.md#policy-any-agent)) |
| `model-tier:heavy` | `Opus` | `Fable`, a tier above `Opus`, is not routed to by any label |

### Codex (OpenAI)

Not checked against OpenAI's own page: its host was unreachable from the session that wrote this, so the rows rest on search results and need a first-hand check.

| Label | Model | Notes |
| --- | --- | --- |
| `model-tier:light` | The smallest current Codex model (`Luna`-named at the time of writing) | |
| `model-tier:medium` | The default Codex model | |
| `model-tier:heavy` | The largest model the Codex picker offers (`Sol` or newer) | |

No label routes to Codex today ([`harness.md`](../harness.md#policy-any-agent) names Claude Code, dsh and Antigravity); this table is the mapping if one does.

### Antigravity (Google)

| Label | Model | Notes |
| --- | --- | --- |
| `model-tier:light` | `Gemini 4 Hydrogen` (`flash`) | |
| `model-tier:medium` | — | No separate medium model in our notes |
| `model-tier:heavy` | `Gemini 4 Neon` | |

Antigravity also offers Claude models, which take their rows from the Claude Code table.

### dsh (DeepSeek Harness)

"dsh" is [DeepSeek Harness](deepseek.md); this page assumes the model it drives is a DeepSeek model, which needs confirming.
Which issues dsh may take is the policy in [`harness.md`](../harness.md#policy-any-agent); since a tiered issue reaches dsh only at `model-tier:light`, this table has no medium or heavy row.

| Label | Model | Notes |
| --- | --- | --- |
| `model-tier:light` | DeepSeek `Flash` | The fast line; the older `deepseek-chat` and `deepseek-reasoner` aliases are reported retired |

## Wide

A `model-context:wide` issue needs a model whose usable window, in the harness as it runs, holds the material; a vendor's advertised window is an upper bound, since a harness may cap or compact it.
These count as wide:

* Claude `Sonnet` and `Opus` (1M-token windows on Anthropic's overview page).
* `Gemini 4 Hydrogen` and `Gemini 4 Neon`.
* DeepSeek `Flash` (a hosted window of about 1M is reported; confirm what dsh's configured endpoint gives).

`Haiku` is not on the list: its price per token is five times higher past a 100K-token prompt, which is why a Haiku builder stops at about 100K ([`harness.md`](../harness.md#policy-any-agent)), and the routing for `light` + `wide` already falls back to `Sonnet` when the material does not fit.
Codex is not on it either: reports say Codex caps a model's window at about 272K tokens although the API advertises about 1M.

## Open questions

* Codex and DeepSeek figures need a check against each vendor's own page from a session whose network allows it.
* Whether any label should route to Codex is a policy choice for `harness.md`, not this page.
