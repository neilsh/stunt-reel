# Models and the routing labels

Which model of each harness stands where on the `model-tier:` and `model-context:` labels.
The labels and their meaning are in [`triage-labels.md`](../agents/triage-labels.md#model-roles), and the routing policy (what a label sends to which harness) is the table in [`harness.md`](../harness.md#policy-any-agent).
This page only says which vendor models are in each capability class, so a model change edits this page and not the labels.

Dated 2026-11-27; vendors change lineups every few months, so refresh it when a harness adds or retires a model, and at least quarterly.
Map by capability class and context window, never by a model name's version number: a new model takes the class its vendor positions it in.

## Capability classes

| Class | Used for | Labels it serves |
| --- | --- | --- |
| Fast | A plan that says exactly what to change; mechanical edits, grading against a rubric | `model-tier:light` |
| Mid | A clear spec where doing it is the work | `model-tier:medium` |
| Flagship | Diagnosis, design, research, rounds of hypotheses | `model-tier:heavy` |
| Wide | A context window that holds the material without compaction | `model-context:wide`, beside any tier |

A `wide` issue needs a model whose usable window, in the harness as it runs, holds the material; a vendor's advertised window is an upper bound, since a harness may cap or compact it.

## Claude Code

Checked against Anthropic's [models overview](https://platform.claude.com/docs/en/about-claude/models/overview), 2026-11-27.

| Class | Model | Notes |
| --- | --- | --- |
| Fast | `Haiku` | Positioned for high-volume, latency-sensitive work |
| Mid | `Sonnet` | The default implementer |
| Flagship | `Opus` | `Fable`, a tier above `Opus`, is not routed to by any label |
| Wide | any of the above | Every current model lists a 1M-token window, so `wide` rarely changes the model on Claude; use the harness's 1M-context option where it is separate |

## Codex (OpenAI)

Not checked against OpenAI's own page: its host was unreachable from the session that wrote this, so the rows rest on search results and need a first-hand check.

| Class | Model | Notes |
| --- | --- | --- |
| Fast | The smallest current Codex model (a `mini` or `Luna`-named tier) | |
| Mid | The default Codex model | |
| Flagship | The largest model the Codex picker offers (`Sol` or newer) | |
| Wide | Codex's window | Reports say Codex catalogs cap a model at about 272K tokens although the API advertises about 1M, so treat Codex as the narrowest `wide` option here |

No label routes to Codex today ([`harness.md`](../harness.md#policy-any-agent) names Claude Code, dsh and Antigravity); this table is the mapping if one does.

## Antigravity (Google)

Model names below are the ones [`harness.md`](../harness.md#antigravity) uses.
The context figures come from search results quoting Google's Gemini API pages, unchecked against the Antigravity docs, whose host was unreachable.

| Class | Model | Notes |
| --- | --- | --- |
| Fast | `Gemini 4 Hydrogen` (`flash`) | Execution turns run here |
| Mid | `Gemini 4 Hydrogen` | No separate mid model in our notes |
| Flagship | `Argon` | The orchestrator and planning model |
| Wide | Gemini models | About a 1M-token input window, but the Antigravity preview compacts near 135K; Antigravity also offers Claude models, with their own windows |

## dsh (DeepSeek Harness)

"dsh" is [DeepSeek Harness](deepseek.md); this page assumes the model it drives is a DeepSeek model, which needs confirming.
Which issues dsh may take is the policy in [`harness.md`](../harness.md#policy-any-agent); since a tiered issue reaches dsh only at `model-tier:light`, this table has no mid or flagship row.

| Class | Model | Notes |
| --- | --- | --- |
| Fast | The DeepSeek model dsh is set to | Its `Flash` line is the fast one; the older `deepseek-chat` and `deepseek-reasoner` aliases are reported retired |
| Wide | The same model | A hosted window of about 1M is reported; open-weight checkpoints are 128K to 160K. Confirm what dsh's configured endpoint gives before sending a `wide` issue there |

## Open questions

* Codex, Antigravity and DeepSeek figures need a check against each vendor's own page from a session whose network allows it.
* Whether any label should route to Codex is a policy choice for `harness.md`, not this page.
