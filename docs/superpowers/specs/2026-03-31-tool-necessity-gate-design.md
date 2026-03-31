# Tool Necessity Gate Design

## 1. Overview

AtlasClaw currently exposes many useful tools to the model, including web search, page fetch, browser automation, memory search, provider integrations, and session/context utilities. The problem is not tool scarcity. The problem is that the runtime does not explicitly decide **when** tool use is mandatory.

As a result, the system may answer questions that should be grounded in current, external, or private data without actually using the relevant tools. This can produce responses that sound plausible but are operationally unsafe, misleading, or unverifiable.

This design introduces a general-purpose runtime policy layer that sits between the incoming user request and the free-form final answer path.

The design has three coordinated layers:

1. **Tool Necessity Gate**
   - Determines whether the request can be answered directly or must use tools/external context.
2. **Capability Matcher**
   - Maps the gate decision to the currently available AtlasClaw tools, providers, and context sources.
3. **Mandatory Tool Enforcement**
   - Prevents the runtime from returning an ungrounded final answer when tools are required.

This is intentionally broader than a fix for weather or "latest information" prompts. It is designed to handle any question whose reliable answer depends on current data, private user context, external systems, browser interaction, or explicit verification.

---

## 2. Problem Statement

### 2.1 Current Runtime Behavior

Today, AtlasClaw:
- injects current time into the system prompt,
- lists available tools in the runtime prompt,
- exposes tools such as `web_search`, `web_fetch`, browser automation, and provider tools,
- relies on the model to decide whether to call them.

That model-first decision path is too weak for reliability-sensitive queries.

### 2.2 Failure Mode

For requests like:
- "2026 清明节上海周边会下雨吗？"
- "上海现在租房哪里便宜？"
- "我在 Jira 里还有哪些待处理工单？"
- "帮我把这篇内容发到知乎"

the current runtime can still allow the model to answer directly, even though the answer depends on:
- current or external information,
- private system data,
- browser/UI interaction,
- or grounded verification.

### 2.3 Design Goal

AtlasClaw must move from:
- "the model has tools available"

to:
- "the runtime knows when a tool-backed answer is required"

The system should explicitly decide when:
- tools are optional,
- tools are preferred,
- tools are mandatory.

---

## 3. Design Goals

### 3.1 Primary Goals

- Prevent ungrounded answers when the request depends on external or changing reality.
- Generalize across classes of questions instead of hardcoding one-off categories.
- Reuse existing AtlasClaw capabilities instead of introducing a separate orchestration stack.
- Preserve extensibility for future tools, provider skills, grounding-style providers, and richer context engines.
- Make the decision process observable and testable.

### 3.2 Non-Goals

This design does not:
- implement a complete replacement for the existing agent runner,
- replace tool execution itself,
- create a new plugin runtime,
- fully implement a separate semantic planner,
- guarantee correctness when no capable tool exists.

---

## 4. Inspiration from OpenClaw

OpenClaw has a richer runtime toolbox, including:
- web search tools,
- grounding-capable providers,
- context-engine concepts,
- hooks/plugins for runtime extension.

However, OpenClaw still depends heavily on configuration, plugins, context strategy, and model behavior to decide whether tools must be used.

AtlasClaw should take inspiration from that richer runtime shape while making the following part more explicit:

- **whether the current request can safely be answered without tools**.

This design therefore strengthens AtlasClaw in a way that is compatible with the OpenClaw direction but more opinionated about runtime grounding discipline.

---

## 5. Architecture Summary

```text
User Request
  -> Tool Necessity Gate
  -> Capability Matcher
  -> Enforcement Policy
  -> Tool-first or answer-direct path
  -> Final Answer
```

### 5.1 New Runtime Policy Components

1. `ToolNecessityGate`
2. `CapabilityMatcher`
3. `ToolEnforcementPolicy`
4. `ResolvedToolPlan`
5. `ToolUseAudit`

### 5.2 Integration Points

These components should integrate with:
- `agent/runner.py`
- `agent/prompt_builder.py`
- `agent/runtime_events.py`
- existing tool registry and tool catalog
- session history and memory systems
- Hook Runtime for observability

---

## 6. Tool Necessity Gate

### 6.1 Responsibility

The Tool Necessity Gate classifies whether the request requires tools or external grounding before the system may produce a final answer.

It must not be limited to one query category like weather. Instead, it should reason over more general dimensions.

### 6.2 Gate Inputs

The gate should evaluate the following sources:
- current user message,
- recent message history,
- session/channel scope,
- authenticated user identity and roles,
- known agent/tool/provider availability,
- optionally lightweight model-based classification.

### 6.3 Decision Dimensions

The gate output should include the following fields:

```json
{
  "needs_tool": true,
  "needs_live_data": true,
  "needs_private_context": false,
  "needs_external_system": false,
  "needs_browser_interaction": false,
  "needs_grounded_verification": true,
  "suggested_tool_classes": ["web_search", "web_fetch"],
  "confidence": 0.92,
  "reason": "The answer depends on current external information and should be verified before finalizing.",
  "policy": "must_use_tool"
}
```

### 6.4 Decision Semantics

- `needs_tool`
  - At least one tool or external capability is required for a reliable answer.
- `needs_live_data`
  - The answer depends on changing current data.
- `needs_private_context`
  - The answer depends on private or user-scoped state.
- `needs_external_system`
  - The answer depends on a provider/platform/system query.
- `needs_browser_interaction`
  - The task requires UI automation rather than only data retrieval.
- `needs_grounded_verification`
  - The answer should be backed by observable evidence before final response.
- `suggested_tool_classes`
  - High-level capability classes, not specific function names yet.
- `policy`
  - One of:
    - `answer_direct`
    - `prefer_tool`
    - `must_use_tool`

### 6.5 Classification Strategy

The gate should use a hybrid strategy:

1. **Static signals**
- Time-sensitive language:
  - now, today, tomorrow, this week, latest, recent, current, forecast, available
- Market/listing language:
  - rent, apartment, listing, vacancy, stock, price, opening, hiring, job
- Action-oriented workflow language:
  - publish, submit, login, click, upload, fill, send
- Private-system language:
  - my Jira, my approvals, my tickets, our Confluence, current session

2. **Context-aware signals**
- Whether the request names a known provider/system.
- Whether the request targets the current user's resources.
- Whether the requested output implies real-world decision risk.

3. **Lightweight model-assisted classification**
- The model may answer an internal control question such as:
  - "Can this request be answered reliably without using tools or current external/private information?"
- This output is internal only.
- The model is not given final authority; it contributes a signal.

### 6.6 Examples

#### Example A: Stable knowledge
Question:
- "法国首都是哪里？"

Likely decision:
- `needs_tool = false`
- `policy = answer_direct`

#### Example B: Time-sensitive public information
Question:
- "清明节上海周边会下雨吗？"

Likely decision:
- `needs_tool = true`
- `needs_live_data = true`
- `needs_grounded_verification = true`
- `policy = must_use_tool`
- `suggested_tool_classes = ["web_search", "web_fetch"]`

#### Example C: Dynamic public listings
Question:
- "上海现在租房哪里便宜？"

Likely decision:
- `needs_tool = true`
- `needs_live_data = true`
- `needs_grounded_verification = true`
- `policy = must_use_tool`
- `suggested_tool_classes = ["web_search", "browser"]`

#### Example D: Private provider state
Question:
- "我在 Jira 里还有哪些待处理工单？"

Likely decision:
- `needs_tool = true`
- `needs_private_context = true`
- `needs_external_system = true`
- `policy = must_use_tool`
- `suggested_tool_classes = ["provider:jira"]`

#### Example E: Browser-driven action
Question:
- "帮我把这篇内容发到知乎"

Likely decision:
- `needs_tool = true`
- `needs_browser_interaction = true`
- `policy = must_use_tool`
- `suggested_tool_classes = ["browser"]`

---

## 7. Capability Matcher

### 7.1 Responsibility

The Capability Matcher maps the gate's abstract requirements to concrete capabilities that exist in the current runtime.

It answers:
- What can this runtime actually use right now?
- Which tools/providers best satisfy the request?
- What should the model prefer or be forced to use?

### 7.2 Input

- gate decision,
- registered executable tools,
- registered provider tools,
- available browser capability,
- current user/provider access context,
- optional Hook-provided or memory-provided context sources.

### 7.3 Output

Example:

```json
{
  "resolved_policy": "must_use_tool",
  "tool_candidates": [
    {
      "name": "web_search",
      "class": "web_search",
      "priority": 100
    },
    {
      "name": "web_fetch",
      "class": "web_fetch",
      "priority": 80
    }
  ],
  "missing_capabilities": [],
  "reason": "Live public information is required and web search tools are available."
}
```

### 7.4 Supported Capability Classes

Initial capability classes should include:
- `web_search`
- `web_fetch`
- `browser`
- `provider:<type>`
- `memory`
- `session`
- `hooks_context`

### 7.5 Matching Rules

1. If a provider-specific capability exists and the request clearly targets that system, prefer the provider capability over generic web search.
2. If the request needs browser interaction, prefer `browser` even if `web_search` is available.
3. If the request depends on private per-user or session data, prefer session/provider/memory capabilities over public web search.
4. If no matching capability exists:
- keep the policy decision,
- expose that the required capability is missing,
- prevent fabricated completion.

### 7.6 Why This Layer Matters

Without the matcher, "needs tool" is too abstract.

The matcher turns runtime policy into something executable by the current tool registry.

---

## 8. Mandatory Tool Enforcement

### 8.1 Responsibility

If the policy says a tool is required, AtlasClaw must not allow a normal final answer path that bypasses tool evidence.

### 8.2 Enforcement Modes

#### `answer_direct`
- No enforced tool requirement.
- The model may answer normally.

#### `prefer_tool`
- Tool usage is encouraged and raised in prompt priority.
- Direct answering is allowed if still reasonable.

#### `must_use_tool`
- The runtime must not accept an ungrounded final answer.
- One of the following must happen:
  1. tool(s) are called successfully,
  2. the runtime enters a controlled tool-first route,
  3. the final answer explicitly states that required verification could not be completed.

### 8.3 Anti-Fabrication Rule

If the runtime has no recorded tool execution evidence, the model must not claim:
- "I searched Bing"
- "I checked online"
- "I verified this just now"
- or any equivalent statement implying external verification.

This must be enforced in both prompt guidance and final-answer validation.

### 8.4 Controlled Tool-First Path

For `must_use_tool`, AtlasClaw may choose one of two strategies:

1. **Model-driven but constrained**
- give the model the resolved tool candidates,
- reinforce that tools are required,
- reject final completion if no evidence was produced.

2. **Runtime-driven prefetch**
- run one or more matched tools first,
- inject the results into context,
- then ask the model to synthesize the answer.

The design should support both. Phase 1 may start with model-driven constrained execution plus final-answer validation.

### 8.5 Failure Behavior

If tool usage is required but fails:
- do not silently fall back to a confident direct answer,
- return a response that clearly states verification failed,
- include what kind of verification was attempted or required.

Example:
- "I couldn't successfully verify current forecast data right now, so I can't reliably answer whether it will rain around Shanghai during Qingming."

---

## 9. Prompt and Context Integration

### 9.1 Prompt Changes

Prompt guidance should be strengthened, but prompt text is not the only control.

The prompt must explicitly state:
- current/live/external/private questions may require tools,
- the model must not invent a search or lookup,
- when the runtime marks tool usage as mandatory, the model should comply before attempting a final answer.

### 9.2 AtlasClaw Context-Engine Role

AtlasClaw does not yet have an explicit standalone "context engine" abstraction like OpenClaw, but it already composes context from:
- session history,
- memory,
- user info,
- provider state,
- hooks,
- tool results.

This design treats the policy pipeline as a front-door control layer that decides whether:
- existing context is enough,
- new tool-generated context must be added,
- or the answer must be blocked until grounding is attempted.

### 9.3 Privileged Tool Result Context

When the policy requires grounding, tool outputs should be treated as privileged context for that turn.

That means:
- tool results should be easier for the model to prioritize than stale memory or generic conversational priors,
- the system should distinguish between grounded evidence and free-form assistant reasoning.

---

## 10. Events and Observability

### 10.1 Why Observability Matters

This policy will affect correctness and user trust. Runtime observability is required.

### 10.2 Event Types

Suggested event taxonomy:
- `tool_gate.evaluated`
- `tool_gate.required`
- `tool_gate.optional`
- `tool_matcher.resolved`
- `tool_matcher.missing_capability`
- `tool_enforcement.blocked_final_answer`
- `tool_enforcement.prefetch_started`
- `tool_enforcement.prefetch_completed`
- `tool_enforcement.prefetch_failed`

### 10.3 Audit Fields

Each policy decision event should include:
- `session_key`
- `run_id`
- `user_id`
- `decision`
- `suggested_tool_classes`
- `resolved_tools`
- `reason`
- `confidence`
- `final_outcome`

### 10.4 Hook Runtime Integration

Heartbeat is already being integrated as an event source. This policy should follow the same design style:
- emit runtime events first,
- let Hook Runtime consume them,
- allow scripts or other future consumers to inspect policy outcomes.

---

## 11. Failure and Safety Model

### 11.1 Safety Principle

The cost of saying "I could not verify this" is lower than the cost of confidently fabricating a tool-backed answer.

### 11.2 When No Tool Exists

If the gate decides the question requires a tool, but the matcher cannot find a suitable capability:
- the system must not pretend the answer is reliable,
- the answer should explain that AtlasClaw lacks the necessary connected capability for this request,
- this should be observable in logs/events.

### 11.3 When Tool Exists but Execution Fails

If the capability exists but execution fails:
- return a constrained explanation,
- do not degrade into a confident unsupported answer.

### 11.4 When the Model Ignores the Policy

If the policy is `must_use_tool` and the model tries to complete directly:
- the runtime should intercept or reject the final answer,
- re-enter the tool path or fail explicitly.

---

## 12. Testing Strategy

### 12.1 Unit Tests

Unit test areas should include:
- gate classification outputs,
- matcher resolution,
- missing-capability behavior,
- enforcement policy transitions,
- anti-fabrication validation.

### 12.2 Integration Tests

Integration tests should cover:
- runner + gate + matcher interaction,
- provider-targeted requests,
- browser-required requests,
- time-sensitive public requests,
- failed tool execution with constrained final response.

### 12.3 E2E Tests

End-to-end cases should include:
- weather/forecast style query that must use web tools,
- dynamic listing query like rent/jobs that must use tools,
- provider-backed private query that must use provider tools,
- browser-action request that must use browser automation,
- stable knowledge query that should not be forced through tools.

---

## 13. Phase Scope

### Phase 1

Phase 1 should implement:
- Tool Necessity Gate output schema,
- Capability Matcher,
- `must_use_tool` enforcement path,
- anti-fabrication rule,
- runtime events for observability,
- prompt guidance updates,
- unit and integration coverage.

### Phase 2

Phase 2 may add:
- more advanced learned heuristics,
- richer capability taxonomies,
- runtime-driven prefetch for more classes of queries,
- explicit context-engine abstraction,
- dashboarding and admin inspection UI.

---

## 14. Recommended Direction

AtlasClaw should not solve this by adding more ad hoc prompt rules for special categories like weather.

The correct direction is to add a general-purpose runtime policy layer that answers:
- Does this question require tools?
- Which tools are appropriate?
- Can the model be allowed to answer without evidence?

That is the role of:
- Tool Necessity Gate
- Capability Matcher
- Mandatory Tool Enforcement

This turns tool use from a suggestion into a governed runtime decision.
