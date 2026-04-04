"""Streaming agent runner built on top of `PydanticAI.iter()`.

The runner adds checkpoint-style controls around agent execution:
- abort-signal checks
- timeout and context checks
- tool-call safety limits
- steering message injection from the session queue

Supported hooks:
`before_agent_start`, `llm_input`, `llm_output`, `before_tool_call`,
`after_tool_call`, and `agent_end`
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from dataclasses import dataclass
from contextlib import asynccontextmanager, nullcontext
from typing import AsyncIterator, Optional, Any, TYPE_CHECKING


logger = logging.getLogger(__name__)

from app.atlasclaw.core.deps import SkillDeps
from app.atlasclaw.agent.stream import StreamEvent
from app.atlasclaw.agent.compaction import CompactionPipeline, CompactionConfig
from app.atlasclaw.agent.history_memory import HistoryMemoryCoordinator
from app.atlasclaw.agent.prompt_builder import PromptBuilder, PromptBuilderConfig
from app.atlasclaw.agent.runner_prompt_context import (
    build_system_prompt,
    collect_tools_snapshot,
)
from app.atlasclaw.agent.runtime_events import RuntimeEventDispatcher
from app.atlasclaw.agent.session_titles import SessionTitleGenerator
from app.atlasclaw.agent.thinking_stream import ThinkingStreamEmitter
from app.atlasclaw.agent.tool_gate import CapabilityMatcher, ToolNecessityGate
from app.atlasclaw.agent.tool_gate_models import CapabilityMatchResult, ToolEnforcementOutcome, ToolGateDecision, ToolPolicyMode
from app.atlasclaw.hooks.runtime import HookRuntime
from app.atlasclaw.session.context import SessionKey

if TYPE_CHECKING:
    from app.atlasclaw.agent.agent_pool import AgentInstancePool
    from app.atlasclaw.agent.token_policy import DynamicTokenPolicy
    from app.atlasclaw.core.token_interceptor import TokenHealthInterceptor


if TYPE_CHECKING:
    from app.atlasclaw.session.manager import SessionManager
    from app.atlasclaw.session.queue import SessionQueue
    from app.atlasclaw.session.router import SessionManagerRouter
    from app.atlasclaw.hooks.system import HookSystem



class _ModelToolGateClassifier:
    """Model-backed classifier used by the runtime when a direct model call is available."""

    def __init__(
        self,
        *,
        runner: "AgentRunner",
        deps: SkillDeps,
        available_tools: list[dict[str, Any]],
        agent: Optional[Any] = None,
        agent_resolver: Optional[Any] = None,
    ) -> None:
        self._runner = runner
        self._agent = agent
        self._agent_resolver = agent_resolver
        self._deps = deps
        self._available_tools = available_tools

    async def _resolve_agent(self) -> Optional[Any]:
        if self._agent is not None:
            return self._agent
        if self._agent_resolver is None:
            return None
        resolved = self._agent_resolver()
        if inspect.isawaitable(resolved):
            resolved = await resolved
        self._agent = resolved
        return resolved

    async def classify(
        self,
        user_message: str,
        recent_history: list[dict[str, Any]],
    ) -> Optional[ToolGateDecision]:
        classifier_agent = await self._resolve_agent()
        if classifier_agent is None:
            return None
        return await self._runner._classify_tool_gate_with_model(
            agent=classifier_agent,
            deps=self._deps,
            user_message=user_message,
            recent_history=recent_history,
            available_tools=self._available_tools,
        )

@dataclass
class _ModelNodeTimeout(RuntimeError):
    """Raised when the model stream stalls waiting for next node."""

    first_node: bool
    timeout_seconds: float


class AgentRunner:
    """Execute a streaming PydanticAI agent with runtime safeguards."""

    REASONING_ONLY_ESCALATION_SECONDS = 6.0
    REASONING_ONLY_MAX_RETRIES = 1
    MODEL_FIRST_NODE_TIMEOUT_SECONDS = 8.0
    MODEL_NEXT_NODE_TIMEOUT_SECONDS = 20.0
    TOOL_GATE_MUST_USE_MIN_CONFIDENCE = 0.85
    TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE = 0.55
    TOOL_GATE_CLASSIFIER_TIMEOUT_SECONDS = 8.0

    def __init__(
        self,
        agent: Any,  # pydantic_ai.Agent
        session_manager: "SessionManager",
        prompt_builder: Optional[PromptBuilder] = None,
        compaction: Optional[CompactionPipeline] = None,
        hook_system: Optional["HookSystem"] = None,
        session_queue: Optional["SessionQueue"] = None,
        session_manager_router: Optional["SessionManagerRouter"] = None,
        hook_runtime: Optional[HookRuntime] = None,
        *,
        agent_id: str = "main",
        token_policy: Optional["DynamicTokenPolicy"] = None,
        agent_pool: Optional["AgentInstancePool"] = None,
        token_interceptor: Optional["TokenHealthInterceptor"] = None,
        agent_factory: Optional[Any] = None,
        tool_gate_model_classifier_enabled: bool = True,
    ):
        """Initialize the agent runner.

        Args:
            agent: PydanticAI agent instance.
            session_manager: Session manager used for transcript persistence.
            prompt_builder: Runtime system prompt builder.
            compaction: Optional compaction pipeline.
            hook_system: Optional hook dispatcher.
            session_queue: Optional queue used for steering message injection.
        """
        self.agent = agent
        self.sessions = session_manager
        self.prompt_builder = prompt_builder or PromptBuilder(PromptBuilderConfig())
        self.compaction = compaction or CompactionPipeline(CompactionConfig())
        self.hooks = hook_system
        self.queue = session_queue
        self.session_manager_router = session_manager_router
        self.agent_id = agent_id
        self.token_policy = token_policy
        self.agent_pool = agent_pool
        self.token_interceptor = token_interceptor
        self.agent_factory = agent_factory
        self.tool_gate_model_classifier_enabled = tool_gate_model_classifier_enabled
        self.history = HistoryMemoryCoordinator(session_manager_router or self.sessions, self.compaction)
        self.runtime_events = RuntimeEventDispatcher(self.hooks, self.queue, hook_runtime)
        self.title_generator = SessionTitleGenerator()
        self.hook_runtime = hook_runtime
        self.tool_gate = ToolNecessityGate()

    
    async def run(
        self,
        session_key: str,
        user_message: str,
        deps: SkillDeps,
        *,
        max_tool_calls: int = 50,
        timeout_seconds: int = 600,
        _token_failover_attempt: int = 0,
        _emit_lifecycle_bounds: bool = True,
    ) -> AsyncIterator[StreamEvent]:
        """Execute one agent turn as a stream of runtime events."""
        start_time = time.monotonic()
        tool_calls_count = 0
        compaction_applied = False
        thinking_emitter = ThinkingStreamEmitter()
        persist_override_messages: Optional[list[dict]] = None
        persist_override_base_len: int = 0
        runtime_agent: Any = self.agent
        selected_token_id: Optional[str] = None
        release_slot: Optional[Any] = None
        flushed_memory_signatures: set[str] = set()
        extra = deps.extra if isinstance(deps.extra, dict) else {}
        run_id = str(extra.get("run_id", "") or "")
        run_failed = False
        message_history: list[dict] = []
        system_prompt = ""
        final_assistant = ""
        context_history_for_hooks: list[dict] = []
        tool_call_summaries: list[dict[str, Any]] = []
        session_title = ""
        buffered_assistant_events: list[StreamEvent] = []
        tool_request_message = user_message
        tool_gate_decision = ToolGateDecision(reason="Tool gate not evaluated yet.")
        tool_match_result = CapabilityMatchResult(
            resolved_policy=ToolPolicyMode.ANSWER_DIRECT,
            tool_candidates=[],
            missing_capabilities=[],
            reason="Tool matcher not evaluated yet.",
        )
        current_model_attempt = 0
        current_attempt_started_at: float | None = None
        current_attempt_has_text = False
        current_attempt_has_tool = False
        reasoning_retry_count = 0
        post_tool_wrap_mode = False
        run_output_start_index = 0


        try:
            if _emit_lifecycle_bounds:
                yield StreamEvent.lifecycle_start()
            yield StreamEvent.runtime_update(
                "reasoning",
                "Starting response analysis.",
                metadata={"phase": "start", "attempt": 0, "elapsed": 0.0},
            )

            runtime_agent, selected_token_id, release_slot = await self._resolve_runtime_agent(session_key, deps)
            runtime_context_window = self._resolve_runtime_context_window(selected_token_id, deps)
            session_manager = self._resolve_session_manager(session_key, deps)

            # --:session + build prompt --

            session = await session_manager.get_or_create(session_key)
            transcript = await session_manager.load_transcript(session_key)
            message_history = self.history.build_message_history(transcript)
            message_history = self.history.prune_summary_messages(message_history)
            context_history_for_hooks = list(message_history)
            session_title = str(getattr(session, "title", "") or "")
            await self.runtime_events.trigger_message_received(
                session_key=session_key,
                run_id=run_id,
                user_message=user_message,
            )
            await self.runtime_events.trigger_run_started(
                session_key=session_key,
                run_id=run_id,
                user_message=user_message,
            )
            await self._maybe_set_draft_title(
                session_manager=session_manager,
                session_key=session_key,
                session=session,
                transcript=transcript,
                user_message=user_message,
            )
            available_tools = collect_tools_snapshot(agent=runtime_agent, deps=deps)
            tool_request_message, used_follow_up_context = self._resolve_contextual_tool_request(
                user_message=user_message,
                recent_history=message_history,
            )
            tool_gate_classifier = self._resolve_tool_gate_classifier(
                agent=runtime_agent,
                deps=deps,
                available_tools=available_tools,
            )
            tool_gate_decision = await self.tool_gate.classify_async(
                tool_request_message,
                message_history,
                classifier=tool_gate_classifier,
            )
            tool_gate_decision = self._normalize_tool_gate_decision(tool_gate_decision)
            tool_gate_decision = self._apply_no_classifier_follow_up_fallback(
                decision=tool_gate_decision,
                used_follow_up_context=used_follow_up_context,
                available_tools=available_tools,
            )
            tool_match_result = CapabilityMatcher(available_tools=available_tools).match(
                tool_gate_decision.suggested_tool_classes
            )
            tool_gate_decision, tool_match_result = self._align_external_system_intent(
                decision=tool_gate_decision,
                match_result=tool_match_result,
                available_tools=available_tools,
            )
            await self.runtime_events.trigger_tool_gate_evaluated(
                session_key=session_key,
                run_id=run_id,
                decision=tool_gate_decision,
            )
            await self.runtime_events.trigger_tool_matcher_resolved(
                session_key=session_key,
                run_id=run_id,
                decision=tool_gate_decision,
                match_result=tool_match_result,
            )

            if (
                tool_gate_decision.policy is ToolPolicyMode.MUST_USE_TOOL
                and tool_match_result.missing_capabilities
            ):
                warning_message = self._build_missing_capability_message(tool_match_result)
                tool_gate_decision = tool_gate_decision.model_copy(
                    update={
                        "policy": ToolPolicyMode.PREFER_TOOL,
                        "reason": (
                            f"{tool_gate_decision.reason} "
                            "Downgraded to prefer_tool because required capabilities are not fully available."
                        ).strip(),
                    }
                )
                yield StreamEvent.runtime_update(
                    "warning",
                    warning_message,
                    metadata={"phase": "gate", "elapsed": round(time.monotonic() - start_time, 1)},
                )

            self._inject_tool_policy(
                deps=deps,
                decision=tool_gate_decision,
                match_result=tool_match_result,
            )

            system_prompt = build_system_prompt(
                self.prompt_builder,
                session=session,
                deps=deps,
                agent=runtime_agent or self.agent,
            )

            if self.hooks:
                prompt_ctx = await self.hooks.trigger(
                    "before_prompt_build",
                    {
                        "session_key": session_key,
                        "user_message": user_message,
                        "system_prompt": system_prompt,
                    },
                )
                system_prompt = prompt_ctx.get("system_prompt", system_prompt)

            # at iter,.
            if self.compaction.should_memory_flush(
                message_history,
                session,
                context_window_override=runtime_context_window,
            ):
                await self.history.flush_history_to_timestamped_memory(
                    session_key=session_key,
                    messages=message_history,
                    deps=deps,
                    session=session,
                    context_window=runtime_context_window,
                    flushed_signatures=flushed_memory_signatures,
                )

            if message_history and self.compaction.should_compact(
                message_history,
                session,
                context_window_override=runtime_context_window,
            ):
                if self.hooks:
                    await self.hooks.trigger(
                        "before_compaction",
                        {
                            "session_key": session_key,
                            "message_count": len(message_history),
                        },
                    )
                yield StreamEvent.compaction_start()
                compressed_history = await self.compaction.compact(message_history, session)
                message_history = self.history.normalize_messages(compressed_history)
                message_history = await self.history.inject_memory_recall(message_history, deps)
                context_history_for_hooks = list(message_history)
                await session_manager.mark_compacted(session_key)
                compaction_applied = True
                yield StreamEvent.compaction_end()
                if self.hooks:
                    await self.hooks.trigger(
                        "after_compaction",
                        {
                            "session_key": session_key,
                            "message_count": len(message_history),
                        },
                    )

            # -- hook:before_agent_start --
            if self.hooks:
                start_ctx = await self.hooks.trigger(
                    "before_agent_start",
                    {
                        "session_key": session_key,
                        "user_message": user_message,
                    },
                )
                user_message = start_ctx.get("user_message", user_message)
            await self.runtime_events.trigger_llm_input(
                session_key=session_key,
                run_id=run_id,
                user_message=user_message,
                system_prompt=system_prompt,
                message_history=message_history,
            )

            # -- inject user_message to deps, for Skills --
            deps.user_message = user_message
            run_output_start_index = len(message_history)

            # ========================================
            # :PydanticAI iter()
            # ========================================
            try:
                model_message_history = self.history.to_model_message_history(message_history)
                async with self._run_iter_with_optional_override(
                    agent=runtime_agent,
                    user_message=user_message,
                    deps=deps,
                    message_history=model_message_history,
                    system_prompt=system_prompt,
                ) as agent_run:

                    node_count = 0
                    try:
                        async for node in self._iter_agent_nodes_with_timeout(agent_run):
                            node_count += 1
                            # -- checkpoint 1:abort_signal --
                            if deps.is_aborted():
                                yield StreamEvent.lifecycle_aborted()
                                break

                            # -- checkpoint 2:--
                            if time.monotonic() - start_time > timeout_seconds:
                                yield StreamEvent.error_event("timeout")
                                break

                            # -- checkpoint 3:context -> trigger --
                            current_messages = self.history.normalize_messages(agent_run.all_messages())
                            current_messages = self.history.prune_summary_messages(current_messages)
                            context_history_for_hooks = list(current_messages)
                            if self.compaction.should_memory_flush(
                                current_messages,
                                session,
                                context_window_override=runtime_context_window,
                            ):
                                await self.history.flush_history_to_timestamped_memory(
                                    session_key=session_key,
                                    messages=current_messages,
                                    deps=deps,
                                    session=session,
                                    context_window=runtime_context_window,
                                    flushed_signatures=flushed_memory_signatures,
                                )

                            if self.compaction.should_compact(
                                current_messages,
                                session,
                                context_window_override=runtime_context_window,
                            ):
                                if self.hooks:
                                    await self.hooks.trigger(
                                        "before_compaction",
                                        {
                                            "session_key": session_key,
                                            "message_count": len(current_messages),
                                        },
                                    )
                                yield StreamEvent.compaction_start()
                                compressed = await self.compaction.compact(current_messages, session)
                                persist_override_messages = self.history.normalize_messages(compressed)
                                persist_override_messages = await self.history.inject_memory_recall(
                                    persist_override_messages,
                                    deps,
                                )
                                context_history_for_hooks = list(persist_override_messages)
                                persist_override_base_len = len(current_messages)
                                await session_manager.mark_compacted(session_key)
                                compaction_applied = True
                                yield StreamEvent.compaction_end()
                                if self.hooks:
                                    await self.hooks.trigger(
                                        "after_compaction",
                                        {
                                            "session_key": session_key,
                                            "message_count": len(persist_override_messages),
                                        },
                                    )
    
                            # -- hook:llm_input() --
                            if self._is_model_request_node(node):
                                current_model_attempt += 1
                                current_attempt_started_at = time.monotonic()
                                current_attempt_has_text = False
                                current_attempt_has_tool = False
                                thinking_emitter.reset_cycle_flags()
                                await self.runtime_events.trigger_llm_input(
                                    session_key=session_key,
                                    run_id=run_id,
                                    user_message=user_message,
                                    system_prompt=system_prompt,
                                    message_history=current_messages,
                                )
                                yield StreamEvent.runtime_update(
                                    "reasoning",
                                    (
                                        "Analyzing request."
                                        if current_model_attempt == 1
                                        else "Continuing reasoning after retry."
                                    ),
                                    metadata={
                                        "phase": "model_request",
                                        "attempt": current_model_attempt,
                                        "elapsed": round(time.monotonic() - start_time, 1),
                                    },
                                )
    
                            # Emit model output chunks as assistant deltas.
                            if hasattr(node, "model_response") and node.model_response:
                                async for event in thinking_emitter.emit_from_model_response(
                                    model_response=node.model_response,
                                    hooks=self.hooks,
                                    session_key=session_key,
                                ):
                                    if (
                                        event.type == "assistant"
                                        and (
                                            (
                                                tool_gate_decision.policy in {
                                                    ToolPolicyMode.MUST_USE_TOOL,
                                                    ToolPolicyMode.PREFER_TOOL,
                                                }
                                                and not tool_call_summaries
                                            )
                                            or post_tool_wrap_mode
                                        )
                                    ):
                                        buffered_assistant_events.append(event)
                                    else:
                                        if event.type == "assistant":
                                            current_attempt_has_text = True
                                        yield event
                            elif hasattr(node, "content") and node.content:
                                content = str(node.content)
                                async for event in thinking_emitter.emit_plain_content(
                                    content=content,
                                    hooks=self.hooks,
                                    session_key=session_key,
                                ):
                                    if (
                                        event.type == "assistant"
                                        and (
                                            (
                                                tool_gate_decision.policy in {
                                                    ToolPolicyMode.MUST_USE_TOOL,
                                                    ToolPolicyMode.PREFER_TOOL,
                                                }
                                                and not tool_call_summaries
                                            )
                                            or post_tool_wrap_mode
                                        )
                                    ):
                                        buffered_assistant_events.append(event)
                                    else:
                                        if event.type == "assistant":
                                            current_attempt_has_text = True
                                        yield event
    
                            # Surface tool activity in the event stream.
                            tool_calls_in_node = self.runtime_events.collect_tool_calls(node)
                            for tool_call in tool_calls_in_node:
                                if isinstance(tool_call, dict):
                                    tool_name = tool_call.get("name", tool_call.get("tool_name", "unknown_tool"))
                                    raw_args = tool_call.get("args", tool_call.get("arguments"))
                                else:
                                    tool_name = getattr(tool_call, "tool_name", getattr(tool_call, "name", "unknown_tool"))
                                    raw_args = getattr(tool_call, "args", getattr(tool_call, "arguments", None))
                                normalized_tool_name = str(tool_name)
                                parsed_args = self._extract_tool_call_arguments(raw_args)
                                summary: dict[str, Any] = {"name": normalized_tool_name}
                                if parsed_args:
                                    summary["args"] = parsed_args
                                tool_call_summaries.append(summary)
                            if tool_calls_in_node:
                                post_tool_wrap_mode = True
                                current_attempt_has_tool = True
                                yield StreamEvent.runtime_update(
                                    "waiting_for_tool",
                                    "Preparing tool execution.",
                                    metadata={
                                        "phase": "planned",
                                        "attempt": current_model_attempt,
                                        "elapsed": round(time.monotonic() - start_time, 1),
                                        "tools": [
                                            (
                                                tool_call.get("name", tool_call.get("tool_name", "unknown_tool"))
                                                if isinstance(tool_call, dict)
                                                else getattr(
                                                    tool_call,
                                                    "tool_name",
                                                    getattr(tool_call, "name", "unknown_tool"),
                                                )
                                            )
                                            for tool_call in tool_calls_in_node
                                        ],
                                    },
                                )
                            tool_dispatch = await self.runtime_events.dispatch_tool_calls(
                                tool_calls_in_node,
                                tool_calls_count=tool_calls_count,
                                max_tool_calls=max_tool_calls,
                                deps=deps,
                                session_key=session_key,
                                run_id=run_id,
                            )
                            tool_calls_count = tool_dispatch.tool_calls_count
                            for event in tool_dispatch.events:
                                yield event
                            if tool_call_summaries and buffered_assistant_events and not post_tool_wrap_mode:
                                while buffered_assistant_events:
                                    yield buffered_assistant_events.pop(0)
                            if (
                                self._is_call_tools_node(node)
                                and not current_attempt_has_text
                                and not current_attempt_has_tool
                                and thinking_emitter.current_cycle_had_thinking
                            ):
                                elapsed_total = round(time.monotonic() - start_time, 1)
                                attempt_elapsed = round(
                                    time.monotonic() - current_attempt_started_at,
                                    1,
                                ) if current_attempt_started_at is not None else elapsed_total
                                should_escalate = (
                                    elapsed_total >= self.REASONING_ONLY_ESCALATION_SECONDS
                                    or reasoning_retry_count >= self.REASONING_ONLY_MAX_RETRIES
                                )
                                if should_escalate:
                                    raise RuntimeError(
                                        "The model did not produce a usable answer after bounded reasoning retries."
                                    )
                                reasoning_retry_count += 1
                                yield StreamEvent.runtime_update(
                                    "retrying",
                                    "Reasoning finished without a usable answer. Retrying with a stricter response policy.",
                                    metadata={
                                        "phase": "retry",
                                        "attempt": reasoning_retry_count,
                                        "elapsed": elapsed_total,
                                        "attempt_elapsed": attempt_elapsed,
                                        "reason": "reasoning_only",
                                    },
                                )
                                if tool_dispatch.should_break:
                                    break
                    except _ModelNodeTimeout as timeout_exc:
                        raise RuntimeError(
                            "The model stream timed out before producing a usable response."
                        ) from timeout_exc

                    # Ensure thinking phase is properly closed if still active.
                    async for event in thinking_emitter.close_if_active():
                        yield event

                    # Persist the final normalized transcript.
                    final_messages = self.history.normalize_messages(agent_run.all_messages())
                    if persist_override_messages is not None:
                        if len(final_messages) > persist_override_base_len > 0:
                            # Preserve override messages and append new run output.
                            final_messages = persist_override_messages + final_messages[persist_override_base_len:]
                        else:
                            final_messages = persist_override_messages
                        run_output_start_index = len(persist_override_messages)

                    final_assistant = self._extract_latest_assistant_from_messages(
                        messages=final_messages,
                        start_index=run_output_start_index,
                    )
                    if post_tool_wrap_mode and tool_call_summaries:
                        wrapped_message = await self._build_post_tool_wrapped_message(
                            runtime_agent=runtime_agent,
                            deps=deps,
                            user_message=user_message,
                            tool_calls=tool_call_summaries,
                        )
                        if wrapped_message:
                            final_assistant = wrapped_message
                            buffered_assistant_events.clear()
                            final_messages = self._replace_last_assistant_message(
                                messages=final_messages,
                                content=wrapped_message,
                            )
                    if buffered_assistant_events and final_assistant:
                        buffered_reasoning_text = self._collect_buffered_assistant_text(
                            buffered_assistant_events
                        )
                        if buffered_reasoning_text:
                            yield StreamEvent.thinking_delta(buffered_reasoning_text)
                            yield StreamEvent.thinking_end(elapsed=0.0)
                        buffered_assistant_events.clear()
                    if buffered_assistant_events and not final_assistant:
                        while buffered_assistant_events:
                            event = buffered_assistant_events.pop(0)
                            if event.type == "assistant":
                                final_assistant += event.content
                            yield event
                        thinking_emitter.assistant_emitted = bool(final_assistant)

                    if not thinking_emitter.assistant_emitted:
                        # Try to get response from agent_run.result first (pydantic-ai structure)
                        if not final_assistant and hasattr(agent_run, "result") and agent_run.result:
                            result = agent_run.result
                            # Try response property first
                            if hasattr(result, "response") and result.response:
                                response = result.response
                                # Extract text content from response parts, excluding thinking parts
                                if hasattr(response, "parts"):
                                    for part in response.parts:
                                        part_kind = getattr(part, "part_kind", "")
                                        # Skip thinking parts, only extract text parts
                                        if part_kind != "thinking" and hasattr(part, "content") and part.content:
                                            content = str(part.content)
                                            if content:
                                                final_assistant = content
                                                break
                                elif hasattr(response, "content") and response.content:
                                    final_assistant = str(response.content)
                            # Try data property as fallback
                            if not final_assistant and hasattr(result, "data") and result.data:
                                final_assistant = str(result.data)
                        
                        # Fallback: search in final_messages
                        if not final_assistant:
                            final_assistant = self._extract_latest_assistant_from_messages(
                                messages=final_messages,
                                start_index=run_output_start_index,
                            )
                        
                        if final_assistant:
                            thinking_emitter.assistant_emitted = True
                            yield StreamEvent.assistant_delta(final_assistant)
                    missing_required_tool_names = self._missing_required_tool_names(
                        decision=tool_gate_decision,
                        match_result=tool_match_result,
                        tool_call_summaries=tool_call_summaries,
                    )
                    if (
                        tool_gate_decision.policy is ToolPolicyMode.MUST_USE_TOOL
                        and missing_required_tool_names
                    ):
                        run_failed = True
                        failure_message = self._build_tool_evidence_required_message(
                            match_result=tool_match_result,
                            missing_required_tools=missing_required_tool_names,
                        )
                        await self.runtime_events.trigger_llm_failed(
                            session_key=session_key,
                            run_id=run_id,
                            error=failure_message,
                        )
                        await self.runtime_events.trigger_run_failed(
                            session_key=session_key,
                            run_id=run_id,
                            error=failure_message,
                        )
                        safe_messages = self._remove_last_assistant_from_run(
                            messages=final_messages,
                            start_index=run_output_start_index,
                        )
                        await session_manager.persist_transcript(session_key, safe_messages)
                        await self.runtime_events.trigger_run_context_ready(
                            session_key=session_key,
                            run_id=run_id,
                            user_message=user_message,
                            system_prompt=system_prompt,
                            message_history=context_history_for_hooks,
                            assistant_message="",
                            tool_calls=tool_call_summaries,
                            run_status="failed",
                            error=failure_message,
                            session_title=session_title,
                        )
                        yield StreamEvent.runtime_update(
                            "failed",
                            failure_message,
                            metadata={
                                "phase": "final",
                                "attempt": current_model_attempt,
                                "elapsed": round(time.monotonic() - start_time, 1),
                            },
                        )
                        yield StreamEvent.error_event(failure_message)
                        buffered_assistant_events.clear()
                        final_assistant = ""
                    else:
                        if not final_assistant.strip():
                            run_failed = True
                            failure_message = "The run ended without a usable final answer."
                            await self.runtime_events.trigger_llm_failed(
                                session_key=session_key,
                                run_id=run_id,
                                error=failure_message,
                            )
                            await self.runtime_events.trigger_run_failed(
                                session_key=session_key,
                                run_id=run_id,
                                error=failure_message,
                            )
                            safe_messages = self._remove_last_assistant_from_run(
                                messages=final_messages,
                                start_index=run_output_start_index,
                            )
                            await session_manager.persist_transcript(session_key, safe_messages)
                            await self.runtime_events.trigger_run_context_ready(
                                session_key=session_key,
                                run_id=run_id,
                                user_message=user_message,
                                system_prompt=system_prompt,
                                message_history=context_history_for_hooks,
                                assistant_message="",
                                tool_calls=tool_call_summaries,
                                run_status="failed",
                                error=failure_message,
                                session_title=session_title,
                            )
                            yield StreamEvent.runtime_update(
                                "failed",
                                failure_message,
                                metadata={
                                    "phase": "final",
                                    "attempt": current_model_attempt,
                                    "elapsed": round(time.monotonic() - start_time, 1),
                                },
                            )
                            yield StreamEvent.error_event(failure_message)
                            buffered_assistant_events.clear()
                            final_assistant = ""
                        else:
                            await self.runtime_events.trigger_llm_completed(
                                session_key=session_key,
                                run_id=run_id,
                                assistant_message=final_assistant,
                            )
                            await session_manager.persist_transcript(session_key, final_messages)
                            await self._maybe_finalize_title(
                                session_manager=session_manager,
                                session_key=session_key,
                                session=session,
                                final_messages=final_messages,
                                user_message=user_message,
                            )
                            session_title = str(getattr(session, "title", "") or "")
                            await self.runtime_events.trigger_run_context_ready(
                                session_key=session_key,
                                run_id=run_id,
                                user_message=user_message,
                                system_prompt=system_prompt,
                                message_history=context_history_for_hooks,
                                assistant_message=final_assistant,
                                tool_calls=tool_call_summaries,
                                run_status="completed",
                                session_title=session_title,
                            )
                            yield StreamEvent.runtime_update(
                                "answered",
                                "Final answer ready.",
                                metadata={
                                    "phase": "final",
                                    "attempt": current_model_attempt,
                                    "elapsed": round(time.monotonic() - start_time, 1),
                                },
                            )

            except Exception as e:
                hard_failure_retried = False
                async for retry_event in self._retry_after_hard_token_failure(
                    error=e,
                    session_key=session_key,
                    user_message=user_message,
                    deps=deps,
                    selected_token_id=selected_token_id,
                    release_slot=release_slot,
                    thinking_emitter=thinking_emitter,
                    start_time=start_time,
                    max_tool_calls=max_tool_calls,
                    timeout_seconds=timeout_seconds,
                    token_failover_attempt=_token_failover_attempt,
                    emit_lifecycle_bounds=_emit_lifecycle_bounds,
                ):
                    hard_failure_retried = True
                    yield retry_event
                if hard_failure_retried:
                    release_slot = None
                    selected_token_id = None
                    return
                run_failed = True
                await self.runtime_events.trigger_llm_failed(
                    session_key=session_key,
                    run_id=run_id,
                    error=str(e),
                )
                await self.runtime_events.trigger_run_failed(
                    session_key=session_key,
                    run_id=run_id,
                    error=str(e),
                )
                await self.runtime_events.trigger_run_context_ready(
                    session_key=session_key,
                    run_id=run_id,
                    user_message=user_message,
                    system_prompt=system_prompt,
                    message_history=context_history_for_hooks,
                    assistant_message=final_assistant,
                    tool_calls=tool_call_summaries,
                    run_status="failed",
                    error=str(e),
                    session_title=session_title,
                )
                # Close thinking phase on exception to maintain contract
                async for event in thinking_emitter.close_if_active():
                    yield event
                        
                # Surface agent runtime errors as stream events.
                yield StreamEvent.runtime_update(
                    "failed",
                    f"Agent runtime error: {str(e)}",
                    metadata={"phase": "exception", "elapsed": round(time.monotonic() - start_time, 1)},
                )
                yield StreamEvent.error_event(f"agent_error: {str(e)}")

            # -- hook:agent_end --
            if not run_failed:
                await self.runtime_events.trigger_agent_end(
                    session_key=session_key,
                    run_id=run_id,
                    tool_calls_count=tool_calls_count,
                    compaction_applied=compaction_applied,
                )

            if _emit_lifecycle_bounds:
                yield StreamEvent.lifecycle_end()

        except Exception as e:
            await self.runtime_events.trigger_run_failed(
                session_key=session_key,
                run_id=run_id,
                error=str(e),
            )
            await self.runtime_events.trigger_run_context_ready(
                session_key=session_key,
                run_id=run_id,
                user_message=user_message,
                system_prompt=system_prompt,
                message_history=context_history_for_hooks,
                assistant_message=final_assistant,
                tool_calls=tool_call_summaries,
                run_status="failed",
                error=str(e),
                session_title=session_title,
            )
            # Close thinking phase on exception to maintain contract
            async for event in thinking_emitter.close_if_active():
                yield event
                
            yield StreamEvent.runtime_update(
                "failed",
                str(e),
                metadata={"phase": "exception", "elapsed": round(time.monotonic() - start_time, 1)},
            )
            yield StreamEvent.error_event(str(e))
        finally:
            if selected_token_id and self.token_interceptor is not None:
                headers = self._extract_rate_limit_headers(deps)
                if headers:
                    self.token_interceptor.on_response(selected_token_id, headers)
            if release_slot is not None:
                release_slot()

    async def _retry_after_hard_token_failure(
        self,
        *,
        error: Exception,
        session_key: str,
        user_message: str,
        deps: SkillDeps,
        selected_token_id: Optional[str],
        release_slot: Optional[Any],
        thinking_emitter: ThinkingStreamEmitter,
        start_time: float,
        max_tool_calls: int,
        timeout_seconds: int,
        token_failover_attempt: int,
        emit_lifecycle_bounds: bool,
    ) -> AsyncIterator[StreamEvent]:
        """Rotate away from a hard-failed token and retry the same run once."""
        if (
            selected_token_id is None
            or self.token_policy is None
            or self.token_interceptor is None
            or not self._is_hard_token_failure(error)
        ):
            return
        max_failover_attempts = max(len(self.token_policy.token_pool.tokens) - 1, 0)
        if token_failover_attempt >= max_failover_attempts:
            return

        extra = deps.extra if isinstance(deps.extra, dict) else {}
        provider = extra.get("provider") if isinstance(extra.get("provider"), str) else None
        model = extra.get("model") if isinstance(extra.get("model"), str) else None
        error_text = str(error)
        self.token_interceptor.on_hard_failure(selected_token_id, error_text)
        next_token = self.token_policy.mark_session_token_unhealthy(
            session_key,
            reason=error_text,
            provider=provider,
            model=model,
        )
        if next_token is None or next_token.token_id == selected_token_id:
            return

        async for event in thinking_emitter.close_if_active():
            yield event
        if release_slot is not None:
            release_slot()

        yield StreamEvent.runtime_update(
            "retrying",
            f"Current model token failed with a provider-side error. Switching to fallback model token `{next_token.token_id}`.",
            metadata={
                "phase": "token_failover",
                "elapsed": round(time.monotonic() - start_time, 1),
                "attempt": token_failover_attempt + 1,
                "failed_token_id": selected_token_id,
                "fallback_token_id": next_token.token_id,
            },
        )
        async for event in self.run(
            session_key=session_key,
            user_message=user_message,
            deps=deps,
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
            _token_failover_attempt=token_failover_attempt + 1,
            _emit_lifecycle_bounds=False,
        ):
            yield event
        if emit_lifecycle_bounds:
            yield StreamEvent.lifecycle_end()
        return

    def _is_hard_token_failure(self, error: Exception) -> bool:
        """Return true when an error indicates the current token should be evicted."""
        lowered = str(error).lower()
        hard_markers = (
            "status_code: 401",
            "status_code: 403",
            "status_code: 429",
            "authenticationerror",
            "accountoverdueerror",
            "forbidden",
            "invalid api key",
            "insufficient_quota",
            "api key format is incorrect",
            "provider returned error', 'code': 429",
            '"code": 429',
            "rate-limited upstream",
            "too many requests",
            "rate limit",
        )
        return any(marker in lowered for marker in hard_markers)

    async def _resolve_runtime_agent(
        self,
        session_key: str,
        deps: SkillDeps,
    ) -> tuple[Any, Optional[str], Optional[Any]]:
        """Resolve runtime agent instance and optional semaphore release callback."""
        if self.token_policy is None or self.agent_pool is None or self.agent_factory is None:
            return self.agent, None, None

        extra = deps.extra if isinstance(deps.extra, dict) else {}
        provider = extra.get("provider") if isinstance(extra.get("provider"), str) else None
        model = extra.get("model") if isinstance(extra.get("model"), str) else None

        token = self.token_policy.get_or_select_session_token(
            session_key,
            provider=provider,
            model=model,
        )
        if token is None:
            return self.agent, None, None

        instance = await self.agent_pool.get_or_create(
            self.agent_id,
            token,
            self.agent_factory,
        )
        await instance.concurrency_sem.acquire()
        return instance.agent, token.token_id, instance.concurrency_sem.release

    def _extract_rate_limit_headers(self, deps: SkillDeps) -> dict[str, str]:
        """Best-effort extraction of ratelimit headers from deps.extra."""
        extra = deps.extra if isinstance(deps.extra, dict) else {}
        candidates = [
            extra.get("rate_limit_headers"),
            extra.get("response_headers"),
            extra.get("llm_response_headers"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                return {str(k): str(v) for k, v in candidate.items()}
        return {}

    def _resolve_runtime_context_window(
        self,
        selected_token_id: Optional[str],
        deps: SkillDeps,
    ) -> Optional[int]:
        """Resolve context window from current runtime model/token settings."""
        # 1) Current selected token metadata (best source).
        if selected_token_id and self.token_policy is not None:
            token = self.token_policy.token_pool.tokens.get(selected_token_id)
            context_window = getattr(token, "context_window", None) if token else None
            if isinstance(context_window, int) and context_window > 0:
                return context_window

        # 2) Request-scoped overrides from deps.extra.
        extra = deps.extra if isinstance(deps.extra, dict) else {}
        extra_window = extra.get("context_window") or extra.get("model_context_window")
        if isinstance(extra_window, int) and extra_window > 0:
            return extra_window

        # 3) Fall back to configured compaction context window.
        return self.compaction.config.context_window

    def _resolve_session_manager(self, session_key: str, deps: SkillDeps) -> Any:
        """Resolve the correct per-user session manager for the active session."""
        parsed = SessionKey.from_string(session_key)
        scoped_manager = getattr(deps, "session_manager", None)
        scoped_user_id = getattr(scoped_manager, "user_id", None)
        if scoped_manager is not None and scoped_user_id == parsed.user_id:
            return scoped_manager
        if self.session_manager_router is not None:
            return self.session_manager_router.for_session_key(session_key)
        return self.sessions

    async def _maybe_set_draft_title(
        self,
        *,
        session_manager: Any,
        session_key: str,
        session: Any,
        transcript: list[Any],
        user_message: str,
    ) -> None:
        """Create a draft title for brand-new chat threads."""
        if getattr(session, "title_status", "empty") not in {"", "empty"}:
            return
        if transcript:
            return
        draft_title = self.title_generator.build_draft_title(user_message)
        await session_manager.update_title(
            session_key,
            title=draft_title,
            title_status="draft",
        )
        session.title = draft_title
        session.title_status = "draft"

    async def _maybe_finalize_title(
        self,
        *,
        session_manager: Any,
        session_key: str,
        session: Any,
        final_messages: list[dict],
        user_message: str,
    ) -> None:
        """Promote a draft title to a stable final title after the first assistant reply."""
        if getattr(session, "title_status", "empty") == "final":
            return
        assistant_message = next(
            (
                msg.get("content", "")
                for msg in final_messages
                if msg.get("role") == "assistant" and msg.get("content")
            ),
            "",
        )
        final_title = self.title_generator.build_final_title(
            first_user_message=user_message,
            first_assistant_message=assistant_message,
            existing_title=getattr(session, "title", ""),
        )
        await session_manager.update_title(
            session_key,
            title=final_title,
            title_status="final",
        )
        session.title = final_title
        session.title_status = "final"

    @asynccontextmanager

    async def _run_iter_with_optional_override(
        self,
        *,
        agent: Any,
        user_message: str,
        deps: SkillDeps,
        message_history: list[dict],
        system_prompt: str,
    ):

        """Run `agent.iter()` with optional system-prompt overrides."""
        override_factory = getattr(agent, "override", None)

        if callable(override_factory) and system_prompt:
            try:
                override_cm = override_factory(system_prompt=system_prompt)
            except TypeError:
                override_cm = nullcontext()
        else:
            override_cm = nullcontext()

        if hasattr(override_cm, "__aenter__"):
            async with override_cm:
                async with agent.iter(
                    user_message,
                    deps=deps,
                    message_history=message_history,
                ) as agent_run:
                    yield agent_run
            return

        with override_cm:
            async with agent.iter(
                user_message,
                deps=deps,
                message_history=message_history,
            ) as agent_run:

                yield agent_run

    async def _iter_agent_nodes_with_timeout(self, agent_run: Any) -> AsyncIterator[Any]:
        iterator = agent_run.__aiter__()
        waiting_for_first_node = True
        while True:
            timeout_seconds = (
                self.MODEL_FIRST_NODE_TIMEOUT_SECONDS
                if waiting_for_first_node
                else self.MODEL_NEXT_NODE_TIMEOUT_SECONDS
            )
            try:
                node = await asyncio.wait_for(iterator.__anext__(), timeout=timeout_seconds)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                raise _ModelNodeTimeout(
                    first_node=waiting_for_first_node,
                    timeout_seconds=float(timeout_seconds),
                ) from exc
            waiting_for_first_node = False
            yield node

    def _is_model_request_node(self, node: Any) -> bool:
        """Return whether a node represents a model request boundary."""
        node_type = type(node).__name__.lower()
        return "modelrequest" in node_type or node_type.endswith("requestnode")

    def _is_call_tools_node(self, node: Any) -> bool:
        """Return whether a node represents the tool-dispatch boundary."""
        node_type = type(node).__name__.lower()
        return "calltools" in node_type

    def _resolve_tool_gate_classifier(
        self,
        *,
        agent: Any,
        deps: SkillDeps,
        available_tools: list[dict[str, Any]],
    ) -> Optional[Any]:
        extra = deps.extra if isinstance(deps.extra, dict) else {}
        explicit_classifier = extra.get("tool_gate_classifier")
        if explicit_classifier is not None:
            return explicit_classifier
        if not self.tool_gate_model_classifier_enabled:
            return None
        classifier_agent = self._select_tool_gate_classifier_agent(agent)
        if classifier_agent is None:
            return None
        return _ModelToolGateClassifier(
            runner=self,
            deps=deps,
            available_tools=available_tools,
            agent=classifier_agent if not callable(classifier_agent) else None,
            agent_resolver=classifier_agent if callable(classifier_agent) else None,
        )

    def _select_tool_gate_classifier_agent(self, runtime_agent: Any) -> Optional[Any]:
        if self.agent_factory is not None and self.token_policy is not None:
            classifier_token = self._select_tool_gate_classifier_token()
            if classifier_token is not None:
                async def _resolver() -> Any:
                    built = self.agent_factory(self.agent_id, classifier_token)
                    if inspect.isawaitable(built):
                        built = await built
                    return built if hasattr(built, "run") else None

                return _resolver
        if hasattr(runtime_agent, "run"):
            return runtime_agent
        return None

    def _select_tool_gate_classifier_token(self) -> Optional[Any]:
        if self.token_policy is None:
            return None
        pool = self.token_policy.token_pool
        ranked: list[tuple[int, int, int, Any]] = []
        for token_id, token in pool.tokens.items():
            health = pool.get_token_health(token_id)
            is_healthy = 1 if (health is None or health.is_healthy) else 0
            ranked.append((is_healthy, int(getattr(token, "priority", 0) or 0), int(getattr(token, "weight", 0) or 0), token))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return ranked[0][3]

    def _normalize_tool_gate_decision(self, decision: ToolGateDecision) -> ToolGateDecision:
        """Normalize gate output and avoid over-aggressive mandatory-tool enforcement."""
        if not isinstance(decision, ToolGateDecision):
            return ToolGateDecision(
                reason="Tool gate decision is invalid; fallback to direct-answer mode.",
                confidence=0.0,
                policy=ToolPolicyMode.ANSWER_DIRECT,
            )

        normalized = decision.model_copy(deep=True)
        normalized.suggested_tool_classes = [
            item.strip()
            for item in normalized.suggested_tool_classes
            if isinstance(item, str) and item.strip()
        ]

        has_provider_skill_hint = any(
            item == "skill" or item.startswith("provider:")
            for item in normalized.suggested_tool_classes
        )
        strict_web_grounding = bool(normalized.needs_live_data)
        strict_provider_or_skill = bool(normalized.needs_external_system) or has_provider_skill_hint
        strict_tool_enforcement = strict_web_grounding or strict_provider_or_skill

        if strict_provider_or_skill:
            normalized.needs_external_system = True
            normalized.needs_tool = True
            if normalized.policy is not ToolPolicyMode.MUST_USE_TOOL:
                normalized.policy = ToolPolicyMode.MUST_USE_TOOL
            normalized.confidence = max(
                normalized.confidence,
                self.TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE,
            )
            if "provider/skill direct tools" not in normalized.reason.lower():
                normalized.reason = (
                    f"{normalized.reason} External-system/provider-skill intent requires direct tool execution."
                ).strip()

        if strict_web_grounding and normalized.policy is not ToolPolicyMode.MUST_USE_TOOL:
            normalized.policy = ToolPolicyMode.MUST_USE_TOOL
            normalized.needs_tool = True
            normalized.confidence = max(
                normalized.confidence,
                self.TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE,
            )
            normalized.reason = (
                f"{normalized.reason} Live grounded requests require tool-backed verification."
            ).strip()

        has_tool_hints = bool(normalized.suggested_tool_classes)
        strict_need = self._tool_gate_has_strict_need(normalized)
        expects_tool = normalized.needs_tool or has_tool_hints or strict_need

        if normalized.policy is ToolPolicyMode.MUST_USE_TOOL and (
            (not strict_tool_enforcement and normalized.confidence < self.TOOL_GATE_MUST_USE_MIN_CONFIDENCE)
            or not expects_tool
            or not strict_need
        ):
            normalized.policy = (
                ToolPolicyMode.PREFER_TOOL
                if expects_tool
                else ToolPolicyMode.ANSWER_DIRECT
            )
            normalized.reason = (
                f"{normalized.reason} Downgraded from must_use_tool due to insufficient confidence or strict-need signals."
            ).strip()

        if normalized.policy is ToolPolicyMode.ANSWER_DIRECT and expects_tool:
            normalized.policy = ToolPolicyMode.PREFER_TOOL

        return normalized

    def _align_external_system_intent(
        self,
        *,
        decision: ToolGateDecision,
        match_result: CapabilityMatchResult,
        available_tools: list[dict[str, Any]],
    ) -> tuple[ToolGateDecision, CapabilityMatchResult]:
        """Prioritize provider/skill tool classes for external-system requests."""
        if not decision.needs_external_system:
            return decision, match_result

        provider_skill_classes = self._collect_provider_skill_capability_classes(available_tools)
        if not provider_skill_classes:
            return decision, match_result

        requested_provider_skill_classes = [
            capability
            for capability in decision.suggested_tool_classes
            if capability == "skill" or capability.startswith("provider:")
        ]
        selected_classes = requested_provider_skill_classes or provider_skill_classes
        selected_classes = [capability for capability in selected_classes if capability in provider_skill_classes]
        if not selected_classes:
            selected_classes = provider_skill_classes

        rewritten = decision.model_copy(deep=True)
        rewritten.needs_tool = True
        rewritten.policy = ToolPolicyMode.MUST_USE_TOOL
        rewritten.confidence = max(rewritten.confidence, self.TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE)
        rewritten.suggested_tool_classes = selected_classes
        rewritten.reason = (
            f"{rewritten.reason} External-system intent was mapped to provider/skill direct tools."
        ).strip()

        refreshed_match = CapabilityMatcher(available_tools=available_tools).match(
            rewritten.suggested_tool_classes
        )
        return rewritten, refreshed_match

    @staticmethod
    def _collect_provider_skill_capability_classes(available_tools: list[dict[str, Any]]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        for tool in available_tools:
            capability = str(tool.get("capability_class", "") or "").strip()
            lowered_name = str(tool.get("name", "") or "").strip().lower()
            lowered_description = str(tool.get("description", "") or "").strip().lower()
            provider_type = str(tool.get("provider_type", "") or "").strip().lower()
            category = str(tool.get("category", "") or "").strip().lower()

            if not capability:
                if provider_type:
                    capability = f"provider:{provider_type}"
                elif "jira" in lowered_name or "jira" in lowered_description:
                    capability = "provider:jira"
                elif category.startswith("provider") or "provider:" in lowered_description:
                    capability = "provider:generic"
                elif "skill" in category or (
                    "skill" in lowered_description and lowered_name not in {"web_search", "web_fetch"}
                ):
                    capability = "skill"

            if not capability:
                continue
            if capability.startswith("provider:") or capability == "skill":
                if capability in seen:
                    continue
                seen.add(capability)
                ordered.append(capability)
        return ordered

    @staticmethod
    def _has_provider_or_skill_candidates(match_result: CapabilityMatchResult) -> bool:
        for candidate in match_result.tool_candidates:
            capability = str(getattr(candidate, "capability_class", "") or "").strip()
            if capability.startswith("provider:") or capability == "skill":
                return True
        return False

    @staticmethod
    def _tool_gate_has_strict_need(decision: ToolGateDecision) -> bool:
        return any(
            [
                bool(decision.needs_live_data),
                bool(decision.needs_grounded_verification),
                bool(decision.needs_external_system),
                bool(decision.needs_browser_interaction),
                bool(decision.needs_private_context),
            ]
        )

    def _resolve_contextual_tool_request(
        self,
        *,
        user_message: str,
        recent_history: list[dict[str, Any]],
    ) -> tuple[str, bool]:
        normalized_user_message = " ".join((user_message or "").split()).strip()
        if not normalized_user_message:
            return user_message, False
        if len(re.sub(r"\s+", "", normalized_user_message)) > 32:
            return normalized_user_message, False

        last_assistant_index: Optional[int] = None
        last_assistant_message = ""
        for index in range(len(recent_history) - 1, -1, -1):
            item = recent_history[index]
            if str(item.get("role", "")).strip() != "assistant":
                continue
            content = " ".join(str(item.get("content", "") or "").split()).strip()
            if not content:
                continue
            last_assistant_index = index
            last_assistant_message = content
            break

        if last_assistant_index is None or not self._looks_like_follow_up_request(last_assistant_message):
            return normalized_user_message, False

        previous_user_message = ""
        for index in range(last_assistant_index - 1, -1, -1):
            item = recent_history[index]
            if str(item.get("role", "")).strip() != "user":
                continue
            content = " ".join(str(item.get("content", "") or "").split()).strip()
            if not content:
                continue
            previous_user_message = content
            break

        if not previous_user_message:
            return normalized_user_message, False

        combined = f"{previous_user_message} {normalized_user_message}".strip()
        return combined, combined != normalized_user_message

    def _apply_no_classifier_follow_up_fallback(
        self,
        *,
        decision: ToolGateDecision,
        used_follow_up_context: bool,
        available_tools: list[dict[str, Any]],
    ) -> ToolGateDecision:
        _ = (used_follow_up_context, available_tools)
        return decision

    def _inject_tool_policy(
        self,
        *,
        deps: SkillDeps,
        decision: ToolGateDecision,
        match_result: CapabilityMatchResult,
    ) -> None:
        """Inject per-run tool-policy context for prompt building."""
        if not isinstance(deps.extra, dict):
            deps.extra = {}

        required_tools: list[str] = []
        for candidate in match_result.tool_candidates:
            name = str(getattr(candidate, "name", "") or "").strip()
            if name and name not in required_tools:
                required_tools.append(name)

        if not required_tools:
            for item in decision.suggested_tool_classes:
                name = str(item or "").strip()
                if name and name not in required_tools:
                    required_tools.append(name)

        if decision.needs_external_system and required_tools:
            provider_skill_names: list[str] = []
            for candidate in match_result.tool_candidates:
                capability = str(getattr(candidate, "capability_class", "") or "").strip()
                name = str(getattr(candidate, "name", "") or "").strip()
                if not name:
                    continue
                if capability.startswith("provider:") or capability == "skill":
                    if name not in provider_skill_names:
                        provider_skill_names.append(name)
            if provider_skill_names:
                required_tools = provider_skill_names

        deps.extra["tool_policy"] = {
            "mode": decision.policy.value,
            "reason": decision.reason,
            "required_tools": required_tools,
            "missing_capabilities": list(match_result.missing_capabilities),
            "confidence": float(decision.confidence),
        }

    @staticmethod
    def _build_missing_capability_message(match_result: CapabilityMatchResult) -> str:
        missing = [item for item in match_result.missing_capabilities if item]
        if missing:
            joined = ", ".join(sorted(set(missing)))
            return (
                "Verification requires tools that are not available. Missing capabilities: "
                f"{joined}. Please enable the corresponding tools and retry."
            )
        return (
            "Verification requires tools that are not available. "
            "Please enable the required tool and retry."
        )

    @staticmethod
    def _collect_buffered_assistant_text(buffered_events: list[StreamEvent]) -> str:
        chunks: list[str] = []
        for event in buffered_events:
            if event.type != "assistant":
                continue
            content = str(getattr(event, "content", "") or "")
            if content:
                chunks.append(content)
        return "".join(chunks).strip()

    @staticmethod
    def _called_tool_names(tool_call_summaries: list[dict[str, Any]]) -> set[str]:
        called: set[str] = set()
        for item in tool_call_summaries:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if name:
                called.add(name)
        return called

    @staticmethod
    def _required_tool_names_for_decision(
        *,
        decision: ToolGateDecision,
        match_result: CapabilityMatchResult,
    ) -> list[str]:
        required: list[str] = []
        for candidate in match_result.tool_candidates:
            capability = str(getattr(candidate, "capability_class", "") or "").strip()
            name = str(getattr(candidate, "name", "") or "").strip()
            if not name:
                continue
            if decision.needs_external_system:
                if capability.startswith("provider:") or capability == "skill":
                    required.append(name)
                continue
            if decision.needs_live_data and decision.needs_grounded_verification:
                if capability in {"weather", "web_search", "web_fetch", "browser"}:
                    required.append(name)
                continue
            required.append(name)

        deduped: list[str] = []
        seen: set[str] = set()
        for name in required:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def _missing_required_tool_names(
        self,
        *,
        decision: ToolGateDecision,
        match_result: CapabilityMatchResult,
        tool_call_summaries: list[dict[str, Any]],
    ) -> list[str]:
        required = self._required_tool_names_for_decision(
            decision=decision,
            match_result=match_result,
        )
        if not required:
            return []
        called = self._called_tool_names(tool_call_summaries)
        return [name for name in required if name not in called]

    @staticmethod
    def _build_tool_evidence_required_message(
        *,
        match_result: CapabilityMatchResult,
        missing_required_tools: list[str],
    ) -> str:
        candidate_names = []
        for candidate in match_result.tool_candidates:
            name = str(getattr(candidate, "name", "") or "").strip()
            if name and name not in candidate_names:
                candidate_names.append(name)
        if missing_required_tools:
            return (
                "A grounded tool-backed answer is required for this request, but required tools were not executed: "
                f"{', '.join(missing_required_tools)}."
            )
        if candidate_names:
            return (
                "A grounded tool-backed answer is required for this request, but no usable tool "
                f"evidence was produced in this run. Required tools: {', '.join(candidate_names)}."
            )
        return (
            "A grounded tool-backed answer is required for this request, but no usable tool "
            "evidence was produced in this run."
        )

    @staticmethod
    def _looks_like_follow_up_request(message: str) -> bool:
        text = " ".join((message or "").split())
        if not text:
            return False
        lowered = text.lower()
        question_count = text.count("?") + text.count("？")
        numbered_choices = len(re.findall(r"(?:^|[\s\n])(?:1[\)\.]|2[\)\.]|3[\)\.])", text))
        interaction_markers = (
            "please reply",
            "reply with",
            "choose",
            "confirm",
            "clarify",
            "specify",
            "select",
            "tell me",
            "provide",
            "\u8bf7\u56de\u590d",
            "\u56de\u590d\u6211",
            "\u8bf7\u786e\u8ba4",
            "\u786e\u8ba4\u4e00\u4e0b",
            "\u8865\u5145",
            "\u544a\u8bc9\u6211",
            "\u9009\u62e9",
            "\u6307\u5b9a",
            "\u9009\u9879",
            "\u4efb\u9009",
        )
        marker_hits = sum(1 for marker in interaction_markers if marker in lowered or marker in text)
        if numbered_choices >= 2 and marker_hits >= 1:
            return True
        if question_count >= 2 and marker_hits >= 1:
            return True
        if question_count >= 1 and marker_hits >= 2:
            return True
        return False

    async def _classify_tool_gate_with_model(
        self,
        *,
        agent: Any,
        deps: SkillDeps,
        user_message: str,
        recent_history: list[dict[str, Any]],
        available_tools: list[dict[str, Any]],
    ) -> Optional[ToolGateDecision]:
        classifier_prompt = self._build_tool_gate_classifier_prompt(available_tools)
        classifier_message = self._build_tool_gate_classifier_message(
            user_message=user_message,
            recent_history=recent_history,
        )
        try:
            raw_output = await asyncio.wait_for(
                self._run_single_with_optional_override(
                    agent=agent,
                    user_message=classifier_message,
                    deps=deps,
                    system_prompt=classifier_prompt,
                ),
                timeout=self.TOOL_GATE_CLASSIFIER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return None
        parsed = self._extract_json_object(raw_output)
        if not parsed:
            return None
        try:
            payload = json.loads(parsed)
            if not isinstance(payload, dict):
                return None
            coerced = self._coerce_tool_gate_payload(payload)
            return ToolGateDecision.model_validate(coerced)
        except Exception:
            return None

    @staticmethod
    def _coerce_tool_gate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        def _read_bool(key: str, default: bool = False) -> bool:
            value = payload.get(key, default)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "y"}:
                    return True
                if lowered in {"false", "0", "no", "n"}:
                    return False
            return default

        suggested = payload.get("suggested_tool_classes", [])
        if isinstance(suggested, str):
            suggested = [part.strip() for part in re.split(r"[,;\n]", suggested) if part.strip()]
        elif not isinstance(suggested, list):
            suggested = []
        suggested = [str(item).strip() for item in suggested if str(item).strip()]

        confidence = payload.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0.0
        confidence_value = max(0.0, min(1.0, confidence_value))

        policy_raw = str(payload.get("policy", ToolPolicyMode.ANSWER_DIRECT.value) or "").strip().lower()
        policy_aliases = {
            "answer": ToolPolicyMode.ANSWER_DIRECT.value,
            "direct": ToolPolicyMode.ANSWER_DIRECT.value,
            "answer_direct": ToolPolicyMode.ANSWER_DIRECT.value,
            "prefer": ToolPolicyMode.PREFER_TOOL.value,
            "prefer_tool": ToolPolicyMode.PREFER_TOOL.value,
            "tool_preferred": ToolPolicyMode.PREFER_TOOL.value,
            "must": ToolPolicyMode.MUST_USE_TOOL.value,
            "must_use": ToolPolicyMode.MUST_USE_TOOL.value,
            "must_use_tool": ToolPolicyMode.MUST_USE_TOOL.value,
            "tool_required": ToolPolicyMode.MUST_USE_TOOL.value,
        }
        policy_value = policy_aliases.get(policy_raw, ToolPolicyMode.ANSWER_DIRECT.value)

        needs_live_data = _read_bool("needs_live_data")
        needs_private_context = _read_bool("needs_private_context")
        needs_external_system = _read_bool("needs_external_system")
        needs_browser_interaction = _read_bool("needs_browser_interaction")
        needs_grounded_verification = _read_bool("needs_grounded_verification")
        needs_tool = _read_bool("needs_tool") or bool(
            suggested
            or needs_live_data
            or needs_private_context
            or needs_external_system
            or needs_browser_interaction
            or needs_grounded_verification
        )

        reason = str(payload.get("reason", "") or "").strip()
        if not reason:
            reason = "Model classifier returned a partial decision; normalized by runtime."

        return {
            "needs_tool": needs_tool,
            "needs_live_data": needs_live_data,
            "needs_private_context": needs_private_context,
            "needs_external_system": needs_external_system,
            "needs_browser_interaction": needs_browser_interaction,
            "needs_grounded_verification": needs_grounded_verification,
            "suggested_tool_classes": suggested,
            "confidence": confidence_value,
            "reason": reason,
            "policy": policy_value,
        }

    def _build_tool_gate_classifier_prompt(self, available_tools: list[dict[str, Any]]) -> str:
        capabilities: list[str] = []
        for tool in available_tools:
            name = str(tool.get("name", "")).strip()
            capability = str(tool.get("capability_class", "")).strip()
            description = str(tool.get("description", "")).strip()
            if capability:
                capabilities.append(f"- {name}: {capability} ({description})")
            else:
                capabilities.append(f"- {name}: {description}")

        capability_text = "\n".join(capabilities) if capabilities else "- no runtime tools available"
        return (
            "You are AtlasClaw's internal tool-necessity classifier.\n"
            "Your job is to decide whether the user request can be answered reliably without tools.\n"
            "Do not answer the user. Do not call tools. Return a single JSON object only.\n\n"
            "Policy rubric:\n"
            "- Use must_use_tool when reliable response requires fresh external facts, enterprise system actions, or verifiable evidence.\n"
            "- If the user asks to query/operate enterprise systems or provider-backed skills, set needs_external_system=true and prefer provider/skill classes over web classes.\n"
            "- Use web_search/web_fetch for public web real-time verification (news, prices, schedules, etc.) when no dedicated domain tool is available.\n"
            "- Do not route provider/skill requests to web_search when provider/skill capabilities are available.\n"
            "- Use prefer_tool when tools would improve confidence but a general direct answer is still acceptable.\n"
            "- Use answer_direct only when the request can be answered reliably from stable knowledge.\n\n"
            "Available runtime capabilities:\n"
            f"{capability_text}\n\n"
            "Return JSON with exactly these fields:\n"
            "{\n"
            '  "needs_tool": boolean,\n'
            '  "needs_live_data": boolean,\n'
            '  "needs_private_context": boolean,\n'
            '  "needs_external_system": boolean,\n'
            '  "needs_browser_interaction": boolean,\n'
            '  "needs_grounded_verification": boolean,\n'
            '  "suggested_tool_classes": string[],\n'
            '  "confidence": number,\n'
            '  "reason": string,\n'
            '  "policy": "answer_direct" | "prefer_tool" | "must_use_tool"\n'
            "}\n"
        )

    def _build_tool_gate_classifier_message(
        self,
        *,
        user_message: str,
        recent_history: list[dict[str, Any]],
    ) -> str:
        history_lines: list[str] = []
        for item in recent_history[-4:]:
            role = str(item.get("role", "")).strip() or "unknown"
            content = str(item.get("content", "")).strip().replace("\n", " ")
            if len(content) > 180:
                content = content[:177] + "..."
            history_lines.append(f"- {role}: {content}")
        history_text = "\n".join(history_lines) if history_lines else "- none"
        return (
            "Classify the following request for runtime policy.\n\n"
            f"User request:\n{user_message}\n\n"
            f"Recent history:\n{history_text}\n"
        )

    async def _run_single_with_optional_override(
        self,
        *,
        agent: Any,
        user_message: str,
        deps: SkillDeps,
        system_prompt: Optional[str] = None,
    ) -> str:
        override_factory = getattr(agent, "override", None)
        if callable(override_factory) and system_prompt:
            try:
                override_cm = override_factory(system_prompt=system_prompt)
            except TypeError:
                override_cm = nullcontext()
        else:
            override_cm = nullcontext()

        if hasattr(override_cm, "__aenter__"):
            async with override_cm:
                result = await agent.run(user_message, deps=deps)
        else:
            with override_cm:
                result = await agent.run(user_message, deps=deps)

        output = result.output if hasattr(result, "output") else result
        return str(output).strip()

    @staticmethod
    def _extract_json_object(raw_output: str) -> str:
        text = (raw_output or "").strip()
        if not text:
            return ""
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return ""
        return text[start : end + 1]

    @staticmethod
    def _extract_tool_call_arguments(raw_args: Any) -> dict[str, Any]:
        if isinstance(raw_args, dict):
            return dict(raw_args)
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    async def _build_post_tool_wrapped_message(
        self,
        *,
        runtime_agent: Any,
        deps: SkillDeps,
        user_message: str,
        tool_calls: list[dict[str, Any]],
    ) -> str:
        """Wrap tool evidence with a concise model-rendered final answer."""
        evidence_items = await self._collect_tool_evidence_items(tool_calls=tool_calls)
        if not evidence_items:
            return ""

        synthesize_system_prompt = (
            "You are a strict response renderer.\n"
            "You receive tool evidence already collected by the runtime.\n"
            "Rules:\n"
            "1) Use only the provided evidence.\n"
            "2) Do not invent facts.\n"
            "3) Preserve numbers, dates, locations, and units exactly.\n"
            "4) Respond in the same language as the user request.\n"
            "5) Keep the answer concise and include source links when available.\n"
            "6) Do not call tools."
        )
        synthesize_user_prompt = (
            f"User request:\n{user_message}\n\n"
            f"Tool evidence (JSON):\n{json.dumps(evidence_items, ensure_ascii=False)}\n\n"
            "Write the final answer for the user."
        )
        try:
            synthesized = await asyncio.wait_for(
                self._run_single_with_optional_override(
                    agent=runtime_agent,
                    user_message=synthesize_user_prompt,
                    deps=deps,
                    system_prompt=synthesize_system_prompt,
                ),
                timeout=6.0,
            )
        except Exception:
            synthesized = ""

        final_text = (synthesized or "").strip()
        if final_text:
            return final_text

        for item in evidence_items:
            result = item.get("result")
            if not isinstance(result, dict):
                continue
            fallback = self._extract_tool_text_result(result)
            if fallback:
                return fallback
        return ""

    async def _collect_tool_evidence_items(
        self,
        *,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            name = str(tool_call.get("name", "") or "").strip()
            args = tool_call.get("args")
            if not name:
                continue
            evidence: dict[str, Any] = {"tool": name}
            if isinstance(args, dict) and args:
                evidence["arguments"] = dict(args)
                tool_result = await self._invoke_tool_evidence_adapter(
                    tool_name=name,
                    tool_args=args,
                )
                if isinstance(tool_result, dict) and not bool(tool_result.get("is_error")):
                    evidence["result"] = tool_result
            items.append(evidence)
        return items

    async def _invoke_tool_evidence_adapter(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if tool_name == "openmeteo_weather":
            return await self._invoke_openmeteo_weather(tool_args=tool_args)
        return None

    async def _invoke_openmeteo_weather(
        self,
        *,
        tool_args: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        try:
            from app.atlasclaw.tools.web.openmeteo_weather_tool import openmeteo_weather_tool
        except Exception:
            return None

        allowed_keys = {
            "location",
            "target_date",
            "days",
            "country_code",
            "timezone",
            "temperature_unit",
            "wind_speed_unit",
            "precipitation_unit",
        }
        safe_args: dict[str, Any] = {}
        for key in allowed_keys:
            if key in tool_args:
                safe_args[key] = tool_args[key]

        location = str(safe_args.get("location", "") or "").strip()
        if not location:
            return None

        days_value = safe_args.get("days")
        if days_value is not None:
            try:
                safe_args["days"] = int(days_value)
            except (TypeError, ValueError):
                safe_args.pop("days", None)

        try:
            result = await openmeteo_weather_tool(None, **safe_args)
        except Exception:
            return None
        return result if isinstance(result, dict) else None

    @staticmethod
    def _extract_tool_text_result(tool_result: dict[str, Any]) -> str:
        content_blocks = tool_result.get("content")
        if not isinstance(content_blocks, list):
            return ""
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = str(block.get("text", "") or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _replace_last_assistant_message(
        *,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        updated = list(messages)
        for index in range(len(updated) - 1, -1, -1):
            item = updated[index]
            if str(item.get("role", "")).strip() != "assistant":
                continue
            replaced = dict(item)
            replaced["content"] = content
            updated[index] = replaced
            return updated
        updated.append({"role": "assistant", "content": content})
        return updated

    @staticmethod
    def _extract_latest_assistant_from_messages(
        *,
        messages: list[dict[str, Any]],
        start_index: int,
    ) -> str:
        if not isinstance(messages, list) or not messages:
            return ""
        safe_start = max(0, min(int(start_index), len(messages)))
        for item in reversed(messages[safe_start:]):
            if not isinstance(item, dict):
                continue
            if str(item.get("role", "")).strip() != "assistant":
                continue
            content = str(item.get("content", "") or "").strip()
            if content:
                return content
        return ""

    @staticmethod
    def _remove_last_assistant_from_run(
        *,
        messages: list[dict[str, Any]],
        start_index: int,
    ) -> list[dict[str, Any]]:
        updated = list(messages)
        safe_start = max(0, min(int(start_index), len(updated)))
        for index in range(len(updated) - 1, safe_start - 1, -1):
            item = updated[index]
            if not isinstance(item, dict):
                continue
            if str(item.get("role", "")).strip() != "assistant":
                continue
            return updated[:index] + updated[index + 1 :]
        return updated

    async def run_single(
        self,
        user_message: str,
        deps: SkillDeps,
        *,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Run a single non-streaming agent call."""
        # Simplified helper that bypasses the streaming session pipeline.
        try:
            result = await self.agent.run(
                user_message,
                deps=deps,
            )
            return result.output if hasattr(result, "output") else str(result)
        except Exception as e:
            return f"[Error: {str(e)}]"



