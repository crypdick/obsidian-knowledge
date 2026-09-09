# 001: Hermes Stop-hook continuation

## Question

Can Hermes address Stop-hook `decision=block` reasons in a continuation of the
same session immediately after a turn, rather than waiting for a later
`pre_llm_call`?

## Current behavior observed from source

- `agent/conversation_loop.py` invokes `pre_llm_call` once before the tool loop and injects plugin context into the current user message.
- The same file invokes `on_session_end` at the very end of every `run_conversation` call, but ignores callback return values.
- `agent/background_review.py` already has a post-response background-thread pattern that forks an `AIAgent`, inherits provider/model/session runtime, runs a maintenance prompt, and can notify the gateway after the main response is delivered.
- `gateway/run.py` already wires `agent.background_review_callback` through post-delivery callbacks so background review messages do not race the main response.

## Approaches considered

### A. Keep using `pre_llm_call`, but skip draining for background review

This prevents background review from consuming queued reminders, but Stop-hook
output still waits for a later, unrelated LLM call. It only partly addresses the
problem and does not match Claude/Codex Stop-hook semantics.

### B. Make `on_session_end` return continuation context and have `run_conversation` loop immediately

This closely matches Stop-hook blocking semantics. However, a synchronous
continuation inside `run_conversation` may delay the original response until
the continuation completes. The user should receive the result first, followed
by the hook response.

### C. Add a dedicated post-response continuation worker, parallel to background review

Reuse the background-review delivery pattern, but do not reuse its memory/skill-only whitelist. The continuation needs the normal session tools because `remember-conversations`, changelog, and index sync may write vault files or run repo commands.

Proposed implementation:

1. Add a plugin hook contract for end-of-turn continuations, e.g. `on_session_end` may return `{"continuation_context": "..."}` or add a new hook such as `post_session_end_continuation`.
2. In `run_conversation`, after the main final response is determined and after normal `on_session_end` fires, collect continuation contexts.
3. If contexts exist, spawn a post-delivery continuation thread with:
   - same `session_id`, platform, runtime, cached system prompt, and conversation history snapshot;
   - bounded max iterations;
   - a clear prompt: address the Stop-hook output, perform required filing/fixes, then stop;
   - a recursion guard so the continuation's own `on_session_end` cannot chain indefinitely except via normal 300s Stop-hook cooldown.
4. Use the same gateway callback/post-delivery release mechanism as background review so the main user response is delivered first and continuation output arrives as a follow-up message in the same topic.
5. Keep the 300s Stop-hook cooldown unchanged.

## Regression tests for a real build

- Plugin unit: `on_session_end` returns/queues exact Stop-hook reasons without global `default` leakage.
- Core unit: `run_conversation` collects continuation context from `on_session_end` return values.
- Core unit: continuation worker is scheduled only after a real final response and not for interrupted turns.
- Core unit: continuation worker carries parent `session_id`/platform and has a recursion guard.
- Gateway unit: post-delivery callback sends the continuation message after the main response to the same chat/thread.
- Integration smoke: user turn triggers Stop-hook reason, main response is delivered, then same-topic continuation files changelog/remember-conversations without waiting for the next user message.

## Recommendation

Implement C in Hermes core, then simplify obsidian-knowledge so Stop-hook reasons are surfaced as explicit continuation requests rather than hidden `pre_llm_call` carryover. Keep `pre_llm_call` carryover only as a compatibility fallback for older Hermes versions or non-continuation runtimes.
