# Models and the routing labels

Maps vendor models and starting effort levels to `model-tier:` ([`triage-labels.md`](../agents/triage-labels.md#model-roles)) and `model-context:wide`; routing policy is in [`harness.md`](../harness.md#policy-any-agent).
Verified 2026-11-28 against vendor docs and this host's T3 catalog; refresh on model changes or quarterly, mapping by vendor tier and usable context window, not version number.

| Harness (effort knob) | `light` | `medium` | `heavy` | `wide` (usable window) |
| --- | --- | --- | --- | --- |
| Claude Code (`effort`) | `Haiku` (`medium`) | `Sonnet` (`medium`) | `Opus` (`high`) | `Sonnet`, `Opus` (1M) |
| Antigravity (`thought_level`) | `Gemini 4 Hydrogen` (`medium`; `flash`) | `Orchestrator (Neon)` (`medium`) | `Orchestrator (Neon)` (`high`) | `Hydrogen`, `Orchestrator (Neon)` (512K); Claude `Sonnet`, `Opus` |
| [dsh](deepseek.md) (`reasoning_effort`) | `deepseek-flash` (`high`) | — | — | `deepseek-flash` (1M) |
| Codex (`reasoningEffort`) | `Luna` (`high`) | `Sol` (`medium`) | `Astra` (`high`) | `Sol` (500K; 1M via `model_context_window`) |

API windows are upper bounds; harnesses may cap or auto-compact earlier.
Parenthesised efforts are starting points: drop to `low` for purely mechanical edits, and step up for stuck diagnosis (`medium` → `high`; `high` → `xhigh` on Claude, Codex and Antigravity Gemini, `max` on dsh, capped at `high` on Antigravity's Claude models).

## Notes

* **Claude Code:** `Fable` sits above `Opus` (unrouted).
  `Haiku` has a 1M window but costs 5× past 100K prompt tokens (input + cache), so it stays off `wide` and stops near 100K.
* **Antigravity:** `Orchestrator (Neon)` pairs `Gemini 4 Neon` (planning) with `Hydrogen` (default executor) and is preferred over standalone `Neon`.
  Gemini 4 API context is 1M; Antigravity documents 512K for `Neon` and publishes no caps for `Hydrogen` or its Claude `Sonnet`/`Opus` subset (no `Haiku`/`Fable`).
* **dsh:** Multi-provider harness configured here for `deepseek-official` / `deepseek-flash` (API also offers `deepseek-v4-pro`); `harness.md` restricts dsh to `light`.
* **Codex:** `Terra` sits between `Luna` and `Sol` for writing, vision, and computer use; `Astra` (272K default) stays off `wide`, and `model_context_window` lives in `config.toml`.
  `Sol` and `Astra` default to `low` in T3, so pass `reasoningEffort` explicitly; OpenAI recommends starting `Luna` at `high`.

Sources: [Claude](https://platform.claude.com/docs/en/models/overview), [Antigravity](https://antigravity.google/docs/models), [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing), [Codex](https://learn.chatgpt.com/docs/models).
