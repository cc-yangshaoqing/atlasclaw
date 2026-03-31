# Current State

## Objective
- Design a Tool Necessity Gate for AtlasClaw so the runtime can decide when an answer must be grounded through tools or external systems instead of relying on free-form model completion.
- Define a unified decision flow covering tool necessity classification, capability matching, and mandatory tool enforcement before implementation starts.

## Completed
- Reviewed canonical architecture, module, and development docs before proposing the design.
- Reviewed the current prompt builder, runner, tool registration, and web search tool path.
- Confirmed AtlasClaw already exposes `web_search`, `web_fetch`, browser, provider tools, Hook Runtime, and session/memory context sources.
- Confirmed the current runtime does not enforce tool usage for time-sensitive or externally-grounded questions; the model is free to answer directly even when tools are needed.
- Identified the current failure mode: time-sensitive and externally-dependent questions can produce confident but ungrounded answers because the system prompt only injects current time and tool availability, not a gating policy.
- Finalized the recommended architecture as a three-layer runtime policy:
  - Tool Necessity Gate
  - Capability Matcher
  - Mandatory Tool Enforcement
- Wrote the initial design spec and task plan for the Tool Necessity Gate workstream.
- Completed a document alignment review across `state`, `task`, and `spec` so the scope, terminology, and next step match.

## In Progress
- Waiting for user review of the written Tool Necessity Gate spec before moving to implementation planning.

## Risks / Decisions
- This feature should solve a general reliability problem, not a narrow "weather query" special case.
- The gate must classify whether the question requires current/live data, private context, external systems, browser interaction, or grounded verification.
- Tool enforcement must not rely solely on model goodwill; once the runtime classifies a request as tool-required, the system must either force the tool path or refuse a final ungrounded answer.
- AtlasClaw should take inspiration from OpenClaw's richer runtime stack (web search, grounding-style providers, context engines, hooks/plugins) while making the tool-necessity policy more explicit than OpenClaw's current default behavior.
- The design should remain compatible with the existing Hook Runtime, memory, and session systems instead of creating a separate orchestration stack.

## Next Step
- Have the user review `docs/superpowers/specs/2026-03-31-tool-necessity-gate-design.md`.
- If approved, write the implementation plan before touching code.
