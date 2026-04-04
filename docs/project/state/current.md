# Current State

## Objective
- Implement Phase 1 of the staged reliability architecture for AtlasClaw so the runtime can decide when answers must be grounded through tools or external systems.
- Define the next-stage provider-driven web search and grounding runtime that can support enterprise-grade retrieval beyond the current HTML-scrape search implementation.
- Keep Full Context Engine work as a separate future track.

## Completed
- Reviewed canonical architecture, module, and development docs.
- Split the design into two specs:
  - Phase 1: Tool Necessity Gate runtime policy
  - Phase 2: Full Context Engine
- Wrote and aligned both specs.
- Wrote the Phase 1 implementation plan.
- Implemented the Phase 1 Tool Necessity Gate runtime skeleton, matcher, runner enforcement path, prompt/runtime event integration, and tests.
- Removed hard-coded keyword-table classification from the core gate.
- Removed the default hidden model-backed pre-classification pass from normal chat turns.
- Model-backed gate classification is now an explicit runtime capability, not a silent default.
- Updated canonical docs to describe the Tool Necessity Gate runtime.
- Completed post-implementation code/task/spec alignment review.
- Completed final standalone code review with no blocking findings.
- Completed verification:
  - targeted Tool Gate tests
  - full backend non-e2e suite
  - full backend e2e suite
  - compileall
  - diff hygiene
- Expanded the Phase 1 spec to include:
  - reasoning-only response handling,
  - bounded retry rules,
  - controlled-path escalation,
  - frontend-visible runtime states and retained thinking display.
- Re-aligned state/task/spec after the expanded Phase 1 scope.
- Implemented the expanded Phase 1 runtime behavior:
  - reasoning-only response detection,
  - bounded retry,
  - controlled-path escalation,
  - retained/toggleable thinking display,
  - frontend runtime visibility for `reasoning`, `retrying`, `waiting_for_tool`, `tool_running`, `controlled_path`, `answered`, and `failed`.
- Completed post-extension code/task/spec alignment review.
- Completed final standalone code review for the expanded Phase 1 implementation.
- Re-verified:
  - full backend non-e2e suite,
  - full frontend suite,
  - full backend e2e suite.
- Reviewed the current `web_search` implementation and confirmed it is still HTML-scrape-first with Bing default and public-search fallback logic.
- Wrote a new spec for a provider-driven web search and grounding runtime.
- Wrote a design-tracking task file for the provider-driven search track.
- Completed a document-alignment review for the provider-driven search `state`, `task`, and `spec`.
- Wrote the provider-driven web search implementation plan.

## In Progress
- Waiting for the user's execution choice for the provider-driven web search implementation plan.

## Risks / Decisions
- Phase 1 must stay narrow and avoid expanding into a full Context Engine rewrite.
- Full Context Engine remains required, but is intentionally deferred to the separate spec and later implementation track.
- The core gate must not depend on static business keyword tables; classification must be driven by explicit classifier decisions with a neutral fallback.
- The runtime must not silently reuse the primary answer model for an extra blocking gate round-trip on every request.
- Reasoning-only model behavior must be handled as a first-class runtime policy problem, not as a frontend-only loading problem.
- Frontend users must be able to observe runtime state progression instead of waiting through silent retries.
- The current HTML-based `web_search` implementation is not sufficient as the long-term enterprise search architecture.
- AtlasClaw search should align with OpenClaw's provider-driven model, but strengthen it with explicit source governance, query recovery, and runtime-policy integration.

## Next Step
- Choose execution mode for the provider-driven web search implementation plan, then implement task-by-task.
