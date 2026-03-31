# Tool Necessity Gate Design Tracking Plan

## Scope
- Design a runtime policy layer that determines when AtlasClaw must use tools or external systems before producing a reliable answer.
- Cover three cooperating layers:
  - Tool Necessity Gate
  - Capability Matcher
  - Mandatory Tool Enforcement
- Keep the design compatible with the current runner, prompt builder, Hook Runtime, tools, sessions, and memory systems.
- Produce a spec that is implementation-ready and scoped for a later implementation plan.

## Deliverables
1. A complete design spec covering classifier inputs, decision outputs, capability matching, enforcement policies, prompt/runtime integration, observability, and testing.
2. Updated project state file with current baseline, risks, and next step.
3. A design-tracking task file that maps the major design decisions to explicit completion criteria.
4. A document alignment review confirming `state`, `task`, and `spec` describe the same scope and next step.

## Design Workstreams

### 1. Baseline and Gap Analysis
Goal: document what exists today and why it is insufficient.

Success criteria:
- [x] Current prompt and runtime flow reviewed.
- [x] Current tool registration path reviewed.
- [x] Existing tools and external capability surfaces listed.
- [x] Gap between "tool availability" and "tool-required enforcement" captured.

Key findings:
- Current time is injected into the prompt, but time-sensitive and externally-dependent questions are not required to use tools.
- AtlasClaw already has `web_search`, `web_fetch`, browser automation, provider tools, Hook Runtime, memory, and session context.
- The current runtime lets the model decide whether to use tools, which can lead to confident but ungrounded answers.

### 2. Runtime Architecture Decision
Goal: choose the policy architecture that sits between user request understanding and tool execution.

Options considered:
- Prompt-only guidance. Rejected because it still depends too much on model self-discipline.
- Rule-only router. Rejected because it will not generalize well across problem types.
- Three-layer policy runtime. Recommended.

Success criteria:
- [x] One recommended architecture selected.
- [x] Rejected alternatives and reasons documented.
- [x] Clear integration boundaries with the current runner and tool stack documented.

Chosen direction:
- Introduce a policy pipeline with:
  - Tool Necessity Gate
  - Capability Matcher
  - Mandatory Tool Enforcement

### 3. Tool Necessity Gate Design
Goal: define how the system classifies whether a question can be answered directly or requires tools.

Success criteria:
- [x] Gate input sources defined.
- [x] Decision schema defined.
- [x] General capability dimensions documented.
- [x] Examples documented beyond weather/time-sensitive questions.

Decision dimensions:
- `needs_tool`
- `needs_live_data`
- `needs_private_context`
- `needs_external_system`
- `needs_browser_interaction`
- `needs_grounded_verification`
- `suggested_tool_classes`
- `reason`

### 4. Capability Matcher Design
Goal: map gate decisions to the currently available AtlasClaw capabilities.

Success criteria:
- [x] Tool-class taxonomy defined.
- [x] Matching logic documented.
- [x] Fallback behavior documented when no matching tool exists.
- [x] Interaction with provider tools and browser tools documented.

Supported capability classes:
- `web_search`
- `web_fetch`
- `browser`
- `provider:<type>`
- `memory`
- `session`
- `hooks_context`

### 5. Mandatory Tool Enforcement Design
Goal: define what happens when tool use is required.

Success criteria:
- [x] Enforcement modes defined.
- [x] Failure behavior defined.
- [x] Anti-fabrication rule documented.
- [x] Final answer gating documented.

Chosen rules:
- If the request is classified as tool-required, AtlasClaw must not allow an ungrounded final answer.
- The runtime may retry with a stronger instruction, route through a controlled tool-first path, or stop with an explicit explanation that verification failed.
- The model must not claim a search or lookup happened unless tool execution evidence exists.

### 6. Prompt and Context Integration
Goal: define how the policy interacts with prompts and runtime context.

Success criteria:
- [x] Prompt updates documented.
- [x] Context engine responsibilities described in AtlasClaw terms.
- [x] Interaction with session history, memory, and hooks documented.

Chosen rules:
- Prompt guidance remains necessary but is no longer the only control.
- The policy pipeline executes before free-form answering.
- Tool results become privileged context when enforcement requires grounding.

### 7. Observability and Events
Goal: make policy decisions observable and reviewable.

Success criteria:
- [x] Event taxonomy defined.
- [x] Log/trace expectations documented.
- [x] Hook Runtime relationship documented.

### 8. Testing Strategy
Goal: ensure the design is concrete enough for later implementation.

Success criteria:
- [x] Unit test scope listed.
- [x] Integration test scope listed.
- [x] E2E scenarios listed.

## Verification
- command: review the current runner, prompt, tools, and docs; then self-review the spec for placeholders, contradictions, and scope drift
- expected: a spec that defines a general tool-necessity policy rather than a one-off fix for weather queries
- actual: spec written at `docs/superpowers/specs/2026-03-31-tool-necessity-gate-design.md`; state/task/spec reviewed for matching scope, terminology, and next step

## Implementation Status
- [ ] Implementation has not started.
- [ ] Wait for user review and approval of the written spec.
- [ ] After approval, write the implementation plan before touching code.

## Handoff Notes
- This workstream is currently at the completed design stage, not implementation.
- The next protocol step is explicit user review of the written spec.
- No code changes should be made until the implementation plan is written and approved for execution.
