# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.atlasclaw.agent.runner import AgentRunner
from app.atlasclaw.auth.models import UserInfo
from app.atlasclaw.core.deps import SkillDeps
from app.atlasclaw.session.manager import SessionManager


class _NoopAgent:
    tools = []

    def iter(self, user_message, deps, message_history):
        raise AssertionError("not used in this unit test")


class _CallToolsNode:
    pass


class _NoAnswerAgentRun:
    def __init__(self, nodes, all_messages):
        self._nodes = nodes
        self._all_messages = all_messages
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def all_messages(self):
        return self._all_messages

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._nodes):
            raise StopAsyncIteration
        node = self._nodes[self._index]
        self._index += 1
        return node


class _NoAnswerAgent:
    tools = [{"name": "web_search", "description": "Web search"}]

    def iter(self, user_message, deps, message_history):
        # Keep history unchanged, and produce a call-tools node with no assistant output.
        return _NoAnswerAgentRun(nodes=[_CallToolsNode()], all_messages=list(message_history))


def _build_runner(tmp_path):
    session_manager = SessionManager(workspace_path=str(tmp_path), user_id="default")
    runner = AgentRunner(agent=_NoopAgent(), session_manager=session_manager)
    deps = SkillDeps(
        user_info=UserInfo(user_id="alice", display_name="alice"),
        session_key="agent:main:user:alice:web:dm:alice:topic:test",
        session_manager=session_manager,
        memory_manager=None,
        cookies={},
        extra={"run_id": "run-test"},
    )
    return runner, deps


@pytest.mark.asyncio
async def test_collect_tool_evidence_items_uses_supported_tool_only(monkeypatch, tmp_path):
    runner, _ = _build_runner(tmp_path)

    async def _fake_invoke(*, tool_args):
        return {
            "is_error": False,
            "content": [{"type": "text", "text": f"weather for {tool_args.get('location', '')}"}],
        }

    monkeypatch.setattr(runner, "_invoke_openmeteo_weather", _fake_invoke)

    items = await runner._collect_tool_evidence_items(
        tool_calls=[
            {"name": "web_search", "args": {"query": "weather"}},
            {"name": "openmeteo_weather", "args": {"location": "Shanghai", "days": 2}},
        ]
    )

    assert len(items) == 2
    assert items[0]["tool"] == "web_search"
    assert items[1]["tool"] == "openmeteo_weather"
    assert items[1]["arguments"]["location"] == "Shanghai"
    assert "result" in items[1]


@pytest.mark.asyncio
async def test_build_post_tool_wrapped_message_prefers_llm_rewrite(monkeypatch, tmp_path):
    runner, deps = _build_runner(tmp_path)

    async def _fake_collect(*, tool_calls):
        return [
            {
                "tool": "openmeteo_weather",
                "arguments": {"location": "Shanghai"},
                "result": {
                    "is_error": False,
                    "content": [{"type": "text", "text": "raw-weather-text"}],
                },
            }
        ]

    async def _fake_single_run(*, agent, user_message, deps, system_prompt=None):
        return "wrapped-weather-answer"

    monkeypatch.setattr(runner, "_collect_tool_evidence_items", _fake_collect)
    monkeypatch.setattr(runner, "_run_single_with_optional_override", _fake_single_run)

    wrapped = await runner._build_post_tool_wrapped_message(
        runtime_agent=SimpleNamespace(),
        deps=deps,
        user_message="Shanghai weather tomorrow",
        tool_calls=[{"name": "openmeteo_weather", "args": {"location": "Shanghai"}}],
    )

    assert wrapped == "wrapped-weather-answer"


@pytest.mark.asyncio
async def test_build_post_tool_wrapped_message_falls_back_to_tool_text(monkeypatch, tmp_path):
    runner, deps = _build_runner(tmp_path)

    async def _fake_collect(*, tool_calls):
        return [
            {
                "tool": "openmeteo_weather",
                "arguments": {"location": "Shanghai"},
                "result": {
                    "is_error": False,
                    "content": [{"type": "text", "text": "raw-weather-text"}],
                },
            }
        ]

    async def _fake_single_run(*, agent, user_message, deps, system_prompt=None):
        raise RuntimeError("synthesize failed")

    monkeypatch.setattr(runner, "_collect_tool_evidence_items", _fake_collect)
    monkeypatch.setattr(runner, "_run_single_with_optional_override", _fake_single_run)

    wrapped = await runner._build_post_tool_wrapped_message(
        runtime_agent=SimpleNamespace(),
        deps=deps,
        user_message="Shanghai weather tomorrow",
        tool_calls=[{"name": "openmeteo_weather", "args": {"location": "Shanghai"}}],
    )

    assert wrapped == "raw-weather-text"


@pytest.mark.asyncio
async def test_runner_does_not_mark_answered_from_stale_history_assistant(tmp_path):
    session_manager = SessionManager(workspace_path=str(tmp_path), user_id="default")
    runner = AgentRunner(
        agent=_NoAnswerAgent(),
        session_manager=session_manager,
        tool_gate_model_classifier_enabled=False,
    )
    deps = SkillDeps(
        user_info=UserInfo(user_id="alice", display_name="alice"),
        session_key="agent:main:user:alice:web:dm:alice:topic:test-stale",
        session_manager=session_manager,
        memory_manager=None,
        cookies={},
        extra={
            "run_id": "run-stale",
            "tools_snapshot": [{"name": "web_search", "description": "Web search"}],
            "tool_gate_classifier": None,
        },
    )

    # Seed a previous assistant response in transcript history.
    await session_manager.persist_transcript(
        deps.session_key,
        [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ],
    )

    events = []
    async for event in runner.run(deps.session_key, "new question", deps):
        events.append(event)

    runtime_states = [
        str(event.metadata.get("state", ""))
        for event in events
        if getattr(event, "type", "") == "runtime"
    ]
    assert "answered" not in runtime_states
    assert "failed" in runtime_states
