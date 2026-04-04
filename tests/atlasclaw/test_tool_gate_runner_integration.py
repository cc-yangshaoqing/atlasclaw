# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.atlasclaw.agent.agent_pool import AgentInstancePool
from app.atlasclaw.agent.runner import AgentRunner
from app.atlasclaw.agent.tool_gate import CapabilityMatcher
from app.atlasclaw.agent.token_policy import DynamicTokenPolicy
from app.atlasclaw.tools.web.provider_runtime import SearchExecutionResponse
from app.atlasclaw.tools.web.provider_models import NormalizedSearchResult
from app.atlasclaw.agent.tool_gate_models import CapabilityMatchResult, ToolCandidate, ToolGateDecision, ToolPolicyMode
from app.atlasclaw.auth.models import UserInfo
from app.atlasclaw.core.token_health_store import TokenHealthStore
from app.atlasclaw.core.token_interceptor import TokenHealthInterceptor
from app.atlasclaw.core.token_pool import TokenEntry, TokenPool
from app.atlasclaw.core.deps import SkillDeps
from app.atlasclaw.hooks.runtime import HookRuntime, HookRuntimeContext
from app.atlasclaw.hooks.runtime_builtin import RUNTIME_AUDIT_MODULE, register_builtin_hook_handlers
from app.atlasclaw.hooks.runtime_models import HookEventType
from app.atlasclaw.hooks.runtime_sinks import ContextSink, MemorySink
from app.atlasclaw.hooks.runtime_store import HookStateStore
from app.atlasclaw.session.manager import SessionManager
from app.atlasclaw.session.queue import SessionQueue
from app.atlasclaw.session.router import SessionManagerRouter


class _NeverCalledAgent:
    def __init__(self) -> None:
        self.calls = 0

    def iter(self, user_message, deps, message_history):
        self.calls += 1
        raise AssertionError("tool gate should block before the model is called")


class _TextNode:
    def __init__(self, content: str):
        self.content = content


class _FakeAgentRun:
    def __init__(self, nodes: list[object], all_messages: list[dict]):
        self._nodes = nodes
        self._all_messages = all_messages
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._nodes):
            raise StopAsyncIteration
        node = self._nodes[self._index]
        self._index += 1
        return node

    def all_messages(self):
        return self._all_messages


class _UngroundedForecastAgent:
    def __init__(self) -> None:
        self.calls = 0
        self.tools = [{"name": "web_search", "description": "Web search"}]

    def iter(self, user_message, deps, message_history):
        self.calls += 1
        final_messages = list(message_history) + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": "明天应该不会下雨。"},
        ]
        return _FakeAgentRun([_TextNode("明天应该不会下雨。")], final_messages)


class _ClassifierResult:
    def __init__(self, decision: ToolGateDecision | None) -> None:
        self._decision = decision

    async def classify(self, user_message: str, recent_history: list[dict]) -> ToolGateDecision | None:
        return self._decision


class _ThinkingPart:
    def __init__(self, content: str) -> None:
        self.part_kind = "thinking"
        self.content = content


class _ModelResponse:
    def __init__(self, *parts: object) -> None:
        self.parts = list(parts)


def _make_model_request_node(*parts: object):
    class ModelRequestNode:
        def __init__(self, model_response):
            self.model_response = model_response

    return ModelRequestNode(_ModelResponse(*parts))


def _make_call_tools_node():
    class CallToolsNode:
        pass

    return CallToolsNode()


def _token(token_id: str, *, provider: str = "doubao", model: str = "gpt-4o") -> TokenEntry:
    return TokenEntry(
        token_id=token_id,
        provider=provider,
        model=model,
        base_url="https://example.com/v1",
        api_key="sk-test",
        api_type="openai",
        priority=0,
        weight=100,
    )


def _build_runner(tmp_path, agent, *, tools: list[dict] | None = None, classifier=None):
    session_manager = SessionManager(workspace_path=str(tmp_path), user_id="default")
    session_router = SessionManagerRouter.from_manager(session_manager)
    hook_state_store = HookStateStore(workspace_path=str(tmp_path))
    hook_runtime = HookRuntime(
        HookRuntimeContext(
            workspace_path=str(tmp_path),
            hook_state_store=hook_state_store,
            memory_sink=MemorySink(str(tmp_path)),
            context_sink=ContextSink(hook_state_store),
            session_manager_router=session_router,
        )
    )
    register_builtin_hook_handlers(hook_runtime)
    runner = AgentRunner(
        agent=agent,
        session_manager=session_manager,
        session_manager_router=session_router,
        session_queue=SessionQueue(),
        hook_runtime=hook_runtime,
        tool_gate_model_classifier_enabled=False,
    )
    deps = SkillDeps(
        user_info=UserInfo(user_id="alice", display_name="alice"),
        session_key="agent:main:user:alice:web:dm:alice:topic:test",
        session_manager=session_router.for_user("alice"),
        memory_manager=None,
        cookies={},
        extra={
            "run_id": "run-1",
            "tools_snapshot": list(tools or []),
            "tool_gate_classifier": classifier,
        },
    )
    return runner, hook_state_store, deps


def test_runner_resolves_follow_up_tool_request_from_clarification_history(tmp_path):
    runner, _, _ = _build_runner(tmp_path, _NeverCalledAgent(), tools=[])

    resolved, used_follow_up_context = runner._resolve_contextual_tool_request(
        user_message="4月6日",
        recent_history=[
            {"role": "user", "content": "上海周日天气"},
            {
                "role": "assistant",
                "content": (
                    "我可以帮你查，但需要你确认是这个周日还是下个周日。"
                    "请回复 1) 这个周日 2) 下个周日。"
                ),
            },
        ],
    )

    assert used_follow_up_context is True
    assert resolved == "上海周日天气 4月6日"


@pytest.mark.asyncio
async def test_runner_follow_up_clarification_without_classifier_short_circuits_into_tool_first_path(
    tmp_path,
):
    class _DirectReplyAgent:
        def __init__(self) -> None:
            self.calls = 0
            self.tools = [{"name": "web_search", "description": "Web search"}]

        def iter(self, user_message, deps, message_history):
            self.calls += 1
            final_messages = list(message_history) + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "已收到，你说的是 4月6日。"},
            ]
            return _FakeAgentRun([_TextNode("已收到，你说的是 4月6日。")], final_messages)

    runner, _, deps = _build_runner(
        tmp_path,
        _DirectReplyAgent(),
        tools=[{"name": "web_search", "description": "Web search"}],
        classifier=None,
    )
    await deps.session_manager.persist_transcript(
        deps.session_key,
        [
            {"role": "system", "content": "AtlasClaw system prompt"},
            {"role": "user", "content": "上海周日天气"},
            {
                "role": "assistant",
                "content": (
                    "我可以帮你查，但需要你确认是这个周日还是下个周日。"
                    "请回复 1) 这个周日 2) 下个周日。"
                ),
            },
        ],
    )

    captured_queries: list[str] = []

    async def _fake_search(**kwargs):
        captured_queries.append(kwargs["query"])
        return (
            SearchExecutionResponse(
                provider="bing_html_fallback",
                query=kwargs["query"],
                results=[
                    NormalizedSearchResult(
                        title="上海天气预报",
                        url="https://www.weather.com.cn/weather/101020100.shtml",
                        snippet="4月6日（周日）多云，15℃到24℃，东北风3级。",
                        provider="bing_html_fallback",
                        rank=1,
                        source_tier="official",
                    )
                ],
            ),
            "",
        )

    runner._execute_controlled_web_search = _fake_search

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="4月6日",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "controlled_path" not in runtime_states
    assert "warning" in runtime_states
    assert captured_queries == []
    assert "failed" not in runtime_states


@pytest.mark.asyncio
async def test_runner_does_not_invoke_hidden_model_classifier_by_default(tmp_path):
    class _DirectAnswerRuntimeAgent:
        def __init__(self) -> None:
            self.calls = 0

        def iter(self, user_message, deps, message_history):
            self.calls += 1
            final_messages = list(message_history) + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "你好，我在。"},
            ]
            return _FakeAgentRun([_TextNode("你好，我在。")], final_messages)

        async def run(self, user_message, deps):
            raise AssertionError("default runtime must not make a hidden classifier model call")

    agent = _DirectAnswerRuntimeAgent()
    runner, _, deps = _build_runner(tmp_path, agent, tools=[])

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="你好",
            deps=deps,
        )
    ]

    assert agent.calls == 1
    assert any(event.type == "assistant" for event in events)


@pytest.mark.asyncio
async def test_runner_blocks_when_tool_required_but_missing_capability(tmp_path):
    agent = _UngroundedForecastAgent()
    classifier = _ClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            needs_live_data=True,
            needs_grounded_verification=True,
            suggested_tool_classes=["web_search"],
            confidence=0.95,
            reason="Classifier requires live web verification.",
            policy=ToolPolicyMode.MUST_USE_TOOL,
        )
    )
    runner, hook_state_store, deps = _build_runner(tmp_path, agent, tools=[], classifier=classifier)

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="清明节上海周边会下雨吗？",
            deps=deps,
        )
    ]

    assert agent.calls == 1
    assert not any(event.type == "error" for event in events)
    stored = await hook_state_store.list_events(RUNTIME_AUDIT_MODULE, "alice")
    event_types = [item.event_type for item in stored]
    assert HookEventType.TOOL_GATE_REQUIRED in event_types
    assert HookEventType.TOOL_MATCHER_RESOLVED in event_types
    assert HookEventType.TOOL_ENFORCEMENT_BLOCKED_FINAL_ANSWER not in event_types


@pytest.mark.asyncio
async def test_runner_blocks_final_answer_when_required_tools_were_not_used(tmp_path):
    agent = _UngroundedForecastAgent()
    classifier = _ClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            needs_live_data=True,
            needs_grounded_verification=True,
            suggested_tool_classes=["web_search"],
            confidence=0.95,
            reason="Classifier requires live web verification.",
            policy=ToolPolicyMode.MUST_USE_TOOL,
        )
    )
    runner, hook_state_store, deps = _build_runner(
        tmp_path,
        agent,
        tools=[{"name": "web_search", "description": "Web search"}],
        classifier=classifier,
    )

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="清明节上海周边会下雨吗？",
            deps=deps,
        )
    ]

    assert agent.calls == 1
    assert not any(event.type == "error" for event in events)
    assert not any(event.type == "assistant" for event in events)
    stored = await hook_state_store.list_events(RUNTIME_AUDIT_MODULE, "alice")
    event_types = [item.event_type for item in stored]
    assert HookEventType.TOOL_GATE_REQUIRED in event_types
    assert HookEventType.TOOL_MATCHER_RESOLVED in event_types
    assert HookEventType.TOOL_ENFORCEMENT_PREFETCH_STARTED not in event_types


@pytest.mark.asyncio
async def test_runner_uses_toolset_snapshot_when_tools_snapshot_is_empty(tmp_path):
    class _ReasoningOnlyToolsetAgent:
        def __init__(self) -> None:
            self.toolsets = [SimpleNamespace(tools={"web_search": {"name": "web_search", "description": "Web search"}})]

        def iter(self, user_message, deps, message_history):
            nodes = [
                _make_model_request_node(_ThinkingPart("First reasoning cycle.")),
                _make_call_tools_node(),
                _make_model_request_node(_ThinkingPart("Second reasoning cycle.")),
                _make_call_tools_node(),
                _make_model_request_node(_ThinkingPart("Third reasoning cycle.")),
                _make_call_tools_node(),
            ]
            return _FakeAgentRun(nodes, list(message_history) + [{"role": "user", "content": user_message}])

    runner, _, deps = _build_runner(tmp_path, _ReasoningOnlyToolsetAgent())

    async def _failed_search(**kwargs):
        return None, "Controlled web search did not return any relevant results."

    runner._execute_controlled_web_search = _failed_search

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="查一下后天上海天气",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "controlled_path" not in runtime_states
    assert "failed" in runtime_states
    assert "answered" not in runtime_states
    assert not any(event.type == "assistant" for event in events)


@pytest.mark.asyncio
async def test_runner_emits_failed_runtime_state_when_tool_verification_never_happens(tmp_path):
    class _ReasoningOnlyMustUseToolAgent:
        def __init__(self) -> None:
            self.tools = [{"name": "web_search", "description": "Web search"}]

        def iter(self, user_message, deps, message_history):
            nodes = [
                _make_model_request_node(_ThinkingPart("Need verification.")),
                _make_call_tools_node(),
                _make_model_request_node(_ThinkingPart("Still need verification.")),
                _make_call_tools_node(),
                _make_model_request_node(_ThinkingPart("No tool call issued.")),
                _make_call_tools_node(),
            ]
            return _FakeAgentRun(nodes, list(message_history) + [{"role": "user", "content": user_message}])

    classifier = _ClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            needs_live_data=True,
            needs_grounded_verification=True,
            suggested_tool_classes=["web_search"],
            confidence=0.99,
            reason="Live verification required.",
            policy=ToolPolicyMode.MUST_USE_TOOL,
        )
    )
    runner, _, deps = _build_runner(
        tmp_path,
        _ReasoningOnlyMustUseToolAgent(),
        tools=[{"name": "web_search", "description": "Web search"}],
        classifier=classifier,
    )

    async def _fake_search(**kwargs):
        return None, "Controlled web search did not return any relevant results."

    runner._execute_controlled_web_search = _fake_search

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="查一下今天上海回武汉怎么走",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "controlled_path" not in runtime_states
    assert "waiting_for_tool" not in runtime_states
    assert "failed" in runtime_states
    assert any(event.type == "error" for event in events)
    assert not any(event.type == "assistant" for event in events)


@pytest.mark.asyncio
async def test_runner_uses_dedicated_classifier_agent_to_short_circuit_tool_first_path(tmp_path):
    class _ClassifierAgent:
        async def run(self, user_message, deps):
            _ = (user_message, deps)
            return SimpleNamespace(
                output=(
                    '{"needs_tool": true, '
                    '"needs_live_data": true, '
                    '"needs_grounded_verification": true, '
                    '"suggested_tool_classes": ["web_search"], '
                    '"confidence": 0.97, '
                    '"reason": "Fresh weather data requires verification.", '
                    '"policy": "must_use_tool"}'
                )
            )

    main_agent = _UngroundedForecastAgent()

    session_manager = SessionManager(workspace_path=str(tmp_path), user_id="default")
    session_router = SessionManagerRouter.from_manager(session_manager)
    hook_state_store = HookStateStore(workspace_path=str(tmp_path))
    hook_runtime = HookRuntime(
        HookRuntimeContext(
            workspace_path=str(tmp_path),
            hook_state_store=hook_state_store,
            memory_sink=MemorySink(str(tmp_path)),
            context_sink=ContextSink(hook_state_store),
            session_manager_router=session_router,
        )
    )
    register_builtin_hook_handlers(hook_runtime)

    token_pool = TokenPool()
    token_pool.register_token(_token("model-1", provider="openrouter", model="openai/gpt-5.4-nano"))
    token_pool.register_token(_token("model-2", provider="openrouter", model="deepseek/deepseek-chat-v3.1"))
    token_policy = DynamicTokenPolicy(token_pool, strategy="health", primary_token_id="model-2")
    token_interceptor = TokenHealthInterceptor(token_pool, TokenHealthStore(str(tmp_path)))
    agent_pool = AgentInstancePool(max_concurrent_per_instance=2)

    async def _factory(agent_id: str, token_entry: TokenEntry):
        _ = agent_id
        if token_entry.token_id == "model-1":
            return _ClassifierAgent()
        return main_agent

    runner = AgentRunner(
        agent=main_agent,
        session_manager=session_manager,
        session_manager_router=session_router,
        session_queue=SessionQueue(),
        hook_runtime=hook_runtime,
        token_policy=token_policy,
        token_interceptor=token_interceptor,
        agent_pool=agent_pool,
        agent_factory=_factory,
        tool_gate_model_classifier_enabled=True,
    )
    deps = SkillDeps(
        user_info=UserInfo(user_id="alice", display_name="alice"),
        session_key="agent:main:user:alice:web:dm:alice:topic:test",
        session_manager=session_router.for_user("alice"),
        memory_manager=None,
        cookies={},
        extra={
            "run_id": "run-classifier",
            "tools_snapshot": [{"name": "web_search", "description": "Web search"}],
        },
    )

    async def _fake_search(**kwargs):
        return (
            SearchExecutionResponse(
                provider="bing_html_fallback",
                query=kwargs["query"],
                results=[
                    NormalizedSearchResult(
                        title="上海天气预报",
                        url="https://www.weather.com.cn/weather/101020100.shtml",
                        snippet="2日（明天）多云转小雨，23℃/14℃。",
                        provider="bing_html_fallback",
                        rank=1,
                    )
                ],
                summary="1. [上海天气预报](https://www.weather.com.cn/weather/101020100.shtml)",
            ),
            "",
        )

    runner._execute_controlled_web_search = _fake_search

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="明天上海天气",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "controlled_path" not in runtime_states
    assert "waiting_for_tool" not in runtime_states
    assert "warning" in runtime_states
    assert main_agent.calls == 1
    assert not any(event.type == "assistant" for event in events)


@pytest.mark.asyncio
async def test_runner_retries_with_fallback_token_after_hard_provider_failure(tmp_path):
    class _OverdueAgent:
        def iter(self, user_message, deps, message_history):
            raise RuntimeError(
                "status_code: 403, model_name: doubao-seed-2-0-pro-260215, body: {'code': 'AccountOverdueError'}"
            )

    class _HealthyAgent:
        def iter(self, user_message, deps, message_history):
            final_messages = list(message_history) + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "明天上海多云转小雨，14℃到22℃。"},
            ]
            return _FakeAgentRun([_TextNode("明天上海多云转小雨，14℃到22℃。")], final_messages)

    session_manager = SessionManager(workspace_path=str(tmp_path), user_id="default")
    session_router = SessionManagerRouter.from_manager(session_manager)
    hook_state_store = HookStateStore(workspace_path=str(tmp_path))
    hook_runtime = HookRuntime(
        HookRuntimeContext(
            workspace_path=str(tmp_path),
            hook_state_store=hook_state_store,
            memory_sink=MemorySink(str(tmp_path)),
            context_sink=ContextSink(hook_state_store),
            session_manager_router=session_router,
        )
    )
    register_builtin_hook_handlers(hook_runtime)

    token_pool = TokenPool()
    token_pool.register_token(_token("model-1", provider="doubao", model="doubao-seed-2-0-pro-260215"))
    token_pool.register_token(_token("model-2", provider="doubao", model="deepseek-v3-2-251201"))
    token_policy = DynamicTokenPolicy(token_pool, strategy="health", primary_token_id="model-1")
    token_interceptor = TokenHealthInterceptor(token_pool, TokenHealthStore(str(tmp_path)))
    agent_pool = AgentInstancePool(max_concurrent_per_instance=2)

    async def _factory(agent_id: str, token_entry: TokenEntry):
        if token_entry.token_id == "model-1":
            return _OverdueAgent()
        return _HealthyAgent()

    runner = AgentRunner(
        agent=_HealthyAgent(),
        session_manager=session_manager,
        session_manager_router=session_router,
        session_queue=SessionQueue(),
        hook_runtime=hook_runtime,
        token_policy=token_policy,
        token_interceptor=token_interceptor,
        agent_pool=agent_pool,
        agent_factory=_factory,
        tool_gate_model_classifier_enabled=False,
    )
    deps = SkillDeps(
        user_info=UserInfo(user_id="alice", display_name="alice"),
        session_key="agent:main:user:alice:web:dm:alice:topic:test",
        session_manager=session_router.for_user("alice"),
        memory_manager=None,
        cookies={},
        extra={"run_id": "run-1"},
    )

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="明天上海天气",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "retrying" in runtime_states
    assert "answered" in runtime_states
    assert any(event.type == "assistant" and "14℃到22℃" in event.content for event in events)
    health = token_pool.get_token_health("model-1")
    assert health is not None
    assert not health.is_healthy
    assert "AccountOverdueError" in health.last_error


@pytest.mark.asyncio
async def test_runner_retries_with_fallback_token_after_rate_limit_failure(tmp_path):
    class _RateLimitedAgent:
        def iter(self, user_message, deps, message_history):
            raise RuntimeError(
                "status_code: 429, model_name: qwen/qwen3.6-plus-preview:free, "
                "body: {'message': 'Provider returned error', 'code': 429}"
            )

    class _HealthyAgent:
        def iter(self, user_message, deps, message_history):
            final_messages = list(message_history) + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "苏州周边徒步可以看灵白线、穹窿山和天平山。"},
            ]
            return _FakeAgentRun(
                [_TextNode("苏州周边徒步可以看灵白线、穹窿山和天平山。")],
                final_messages,
            )

    session_manager = SessionManager(workspace_path=str(tmp_path), user_id="default")
    session_router = SessionManagerRouter.from_manager(session_manager)
    hook_state_store = HookStateStore(workspace_path=str(tmp_path))
    hook_runtime = HookRuntime(
        HookRuntimeContext(
            workspace_path=str(tmp_path),
            hook_state_store=hook_state_store,
            memory_sink=MemorySink(str(tmp_path)),
            context_sink=ContextSink(hook_state_store),
            session_manager_router=session_router,
        )
    )
    register_builtin_hook_handlers(hook_runtime)

    token_pool = TokenPool()
    token_pool.register_token(_token("model-1", provider="openrouter", model="qwen/qwen3.6-plus-preview:free"))
    token_pool.register_token(_token("model-2", provider="openrouter", model="deepseek/deepseek-chat-v3.1"))
    token_policy = DynamicTokenPolicy(token_pool, strategy="health", primary_token_id="model-1")
    token_interceptor = TokenHealthInterceptor(token_pool, TokenHealthStore(str(tmp_path)))
    agent_pool = AgentInstancePool(max_concurrent_per_instance=2)

    async def _factory(agent_id: str, token_entry: TokenEntry):
        if token_entry.token_id == "model-1":
            return _RateLimitedAgent()
        return _HealthyAgent()

    runner = AgentRunner(
        agent=_HealthyAgent(),
        session_manager=session_manager,
        session_manager_router=session_router,
        session_queue=SessionQueue(),
        hook_runtime=hook_runtime,
        token_policy=token_policy,
        token_interceptor=token_interceptor,
        agent_pool=agent_pool,
        agent_factory=_factory,
        tool_gate_model_classifier_enabled=False,
    )
    deps = SkillDeps(
        user_info=UserInfo(user_id="alice", display_name="alice"),
        session_key="agent:main:user:alice:web:dm:alice:topic:test",
        session_manager=session_router.for_user("alice"),
        memory_manager=None,
        cookies={},
        extra={"run_id": "run-429"},
    )

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="上海周边徒步",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "retrying" in runtime_states
    assert "answered" in runtime_states
    assert any(event.type == "assistant" and "灵白线" in event.content for event in events)
    health = token_pool.get_token_health("model-1")
    assert health is not None
    assert not health.is_healthy
    assert "status_code: 429" in health.last_error

@pytest.mark.asyncio
async def test_runner_prefer_tool_short_circuits_without_strict_need(tmp_path):
    class _DirectAnswerAgent:
        def __init__(self) -> None:
            self.calls = 0
            self.tools = [{"name": "web_search", "description": "Web search"}]

        def iter(self, user_message, deps, message_history):
            self.calls += 1
            final_messages = list(message_history) + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "推荐你去佘山、辰山植物园和东平国家森林公园徒步。"},
            ]
            return _FakeAgentRun(
                [_TextNode("推荐你去佘山、辰山植物园和东平国家森林公园徒步。")],
                final_messages,
            )

    classifier = _ClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            needs_live_data=False,
            needs_grounded_verification=False,
            suggested_tool_classes=["web_search"],
            confidence=0.90,
            reason="Prefer verification through search.",
            policy=ToolPolicyMode.PREFER_TOOL,
        )
    )
    agent = _DirectAnswerAgent()
    runner, _, deps = _build_runner(
        tmp_path,
        agent,
        tools=[{"name": "web_search", "description": "Web search"}],
        classifier=classifier,
    )

    async def _fake_search(**kwargs):
        return (
            SearchExecutionResponse(
                provider="duckduckgo_html_fallback",
                query=kwargs["query"],
                results=[
                    NormalizedSearchResult(
                        title="当天就能来回!上海周边6个适合爬山徒步的地方!沿途风景绝美",
                        url="https://zhuanlan.zhihu.com/p/1942515419350045860",
                        snippet="",
                        provider="duckduckgo_html_fallback",
                        rank=1,
                        source_tier="unknown",
                    )
                ],
            ),
            "",
        )

    runner._execute_controlled_web_search = _fake_search

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="上海周边有啥地方可以徒步呢",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "controlled_path" not in runtime_states
    assert "answered" in runtime_states
    assert "failed" not in runtime_states
    assert agent.calls == 1


@pytest.mark.asyncio
async def test_runner_strict_need_tool_failure_does_not_fall_back_to_clarifying_direct_response(tmp_path):
    class _ClarifyingRuntimeAgent:
        def __init__(self) -> None:
            self.tools = [{"name": "web_search", "description": "Web search"}]
            self.run_calls = 0

        def iter(self, user_message, deps, message_history):
            nodes = [
                _make_model_request_node(_ThinkingPart("Need verification.")),
                _make_call_tools_node(),
            ]
            return _FakeAgentRun(nodes, list(message_history) + [{"role": "user", "content": user_message}])

        async def run(self, user_message, deps):
            self.run_calls += 1
            return SimpleNamespace(
                output="我可以帮你查，但请先确认具体日期，并从以下来源里选一个。"
            )

    classifier = _ClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            needs_live_data=True,
            needs_grounded_verification=True,
            suggested_tool_classes=["web_search"],
            confidence=0.85,
            reason="Live verification preferred.",
            policy=ToolPolicyMode.PREFER_TOOL,
        )
    )
    agent = _ClarifyingRuntimeAgent()
    runner, _, deps = _build_runner(
        tmp_path,
        agent,
        tools=[{"name": "web_search", "description": "Web search"}],
        classifier=classifier,
    )

    async def _failed_search(**kwargs):
        return None, "Controlled web search did not return any relevant results."

    runner._execute_controlled_web_search = _failed_search

    events = [
        event
        async for event in runner.run(
            session_key=deps.session_key,
            user_message="上海周日天气",
            deps=deps,
        )
    ]

    runtime_states = [event.metadata.get("state") for event in events if event.type == "runtime"]
    assert "controlled_path" not in runtime_states
    assert "failed" not in runtime_states
    assert "warning" in runtime_states
    assistant_messages = [event.content for event in events if event.type == "assistant"]
    assert len(assistant_messages) == 0
    assert not any("请先确认" in message for message in assistant_messages)
    assert agent.run_calls == 0


def test_align_external_system_intent_prefers_provider_skill_over_web(tmp_path):
    runner, _, _ = _build_runner(
        tmp_path,
        _NeverCalledAgent(),
        tools=[
            {"name": "web_search", "description": "Web search", "capability_class": "web_search"},
            {
                "name": "jira_search",
                "description": "Search Jira issues",
                "capability_class": "provider:jira",
            },
        ],
        classifier=None,
    )
    decision = ToolGateDecision(
        needs_tool=True,
        needs_live_data=True,
        needs_external_system=True,
        needs_grounded_verification=True,
        suggested_tool_classes=["web_search"],
        confidence=0.9,
        reason="Need enterprise data.",
        policy=ToolPolicyMode.MUST_USE_TOOL,
    )
    initial_match = CapabilityMatcher(
        available_tools=[
            {"name": "web_search", "description": "Web search", "capability_class": "web_search"},
            {
                "name": "jira_search",
                "description": "Search Jira issues",
                "capability_class": "provider:jira",
            },
        ]
    ).match(decision.suggested_tool_classes)

    rewritten, refreshed_match = runner._align_external_system_intent(
        decision=decision,
        match_result=initial_match,
        available_tools=[
            {"name": "web_search", "description": "Web search", "capability_class": "web_search"},
            {
                "name": "jira_search",
                "description": "Search Jira issues",
                "capability_class": "provider:jira",
            },
        ],
    )

    assert rewritten.policy is ToolPolicyMode.MUST_USE_TOOL
    assert rewritten.needs_external_system is True
    assert rewritten.suggested_tool_classes == ["provider:jira"]
    assert [candidate.name for candidate in refreshed_match.tool_candidates] == ["jira_search"]


def test_missing_required_tool_names_requires_provider_tool_execution(tmp_path):
    runner, _, _ = _build_runner(tmp_path, _NeverCalledAgent(), tools=[], classifier=None)
    decision = ToolGateDecision(
        needs_tool=True,
        needs_external_system=True,
        needs_grounded_verification=True,
        suggested_tool_classes=["provider:jira"],
        confidence=0.95,
        reason="Need enterprise system query.",
        policy=ToolPolicyMode.MUST_USE_TOOL,
    )
    match_result = CapabilityMatchResult(
        resolved_policy=ToolPolicyMode.MUST_USE_TOOL,
        tool_candidates=[
            ToolCandidate(name="jira_search", capability_class="provider:jira", priority=120),
        ],
        missing_capabilities=[],
        reason="matched",
    )

    missing = runner._missing_required_tool_names(
        decision=decision,
        match_result=match_result,
        tool_call_summaries=[{"name": "web_search"}],
    )
    assert missing == ["jira_search"]
    assert runner._missing_required_tool_names(
        decision=decision,
        match_result=match_result,
        tool_call_summaries=[{"name": "jira_search"}],
    ) == []


def test_normalize_tool_gate_decision_forces_must_use_for_provider_skill_hints(tmp_path):
    runner, _, _ = _build_runner(tmp_path, _NeverCalledAgent(), tools=[], classifier=None)
    decision = ToolGateDecision(
        needs_tool=True,
        needs_external_system=False,
        needs_grounded_verification=False,
        suggested_tool_classes=["provider:jira"],
        confidence=0.1,
        reason="Classifier returned provider hint.",
        policy=ToolPolicyMode.ANSWER_DIRECT,
    )

    normalized = runner._normalize_tool_gate_decision(decision)

    assert normalized.needs_external_system is True
    assert normalized.policy is ToolPolicyMode.MUST_USE_TOOL
    assert normalized.confidence >= runner.TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE


def test_normalize_tool_gate_decision_forces_must_use_for_live_grounded_requests(tmp_path):
    runner, _, _ = _build_runner(tmp_path, _NeverCalledAgent(), tools=[], classifier=None)
    decision = ToolGateDecision(
        needs_tool=True,
        needs_live_data=True,
        needs_grounded_verification=True,
        suggested_tool_classes=["web_search"],
        confidence=0.2,
        reason="Classifier asks for live grounding.",
        policy=ToolPolicyMode.ANSWER_DIRECT,
    )

    normalized = runner._normalize_tool_gate_decision(decision)

    assert normalized.policy is ToolPolicyMode.MUST_USE_TOOL
    assert normalized.needs_tool is True
    assert normalized.confidence >= runner.TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE


