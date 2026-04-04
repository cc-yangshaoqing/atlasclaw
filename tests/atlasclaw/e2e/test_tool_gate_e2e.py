# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.atlasclaw.agent.runner import AgentRunner
from app.atlasclaw.api.routes import APIContext, create_router, set_api_context
from app.atlasclaw.hooks.runtime import HookRuntime, HookRuntimeContext
from app.atlasclaw.hooks.runtime_sinks import ContextSink, MemorySink
from app.atlasclaw.hooks.runtime_store import HookStateStore
from app.atlasclaw.session.manager import SessionManager
from app.atlasclaw.session.queue import SessionQueue
from app.atlasclaw.session.router import SessionManagerRouter
from app.atlasclaw.skills.registry import SkillRegistry


class _TextNode:
    def __init__(self, content: str):
        self.content = content


class _RunResult:
    def __init__(self, output: str):
        self.output = output


class _ClassifierAndAnswerAgent:
    tools = [
        {"name": "web_search", "description": "Web search"},
        {"name": "web_fetch", "description": "Fetch webpage content"},
    ]

    def __init__(self) -> None:
        self.iter_calls = 0

    async def run(self, user_message, deps):
        if "Classify the following request for runtime policy." in str(user_message):
            return _RunResult(
                json.dumps(
                    {
                        "needs_tool": True,
                        "needs_live_data": True,
                        "needs_private_context": False,
                        "needs_external_system": False,
                        "needs_browser_interaction": False,
                        "needs_grounded_verification": True,
                        "suggested_tool_classes": ["web_search"],
                        "confidence": 0.97,
                        "reason": "Live weather query requires web verification.",
                        "policy": "must_use_tool",
                    }
                )
            )
        return _RunResult(
            "上海周日有小雨风险，气温约15-21℃。\n\n来源：https://www.weather.com.cn/weather/101020100.shtml"
        )

    def iter(self, user_message, deps, message_history):
        self.iter_calls += 1
        raise AssertionError("short-circuit controlled path should not call iter()")


class _PreferToolClassifierAgent:
    tools = [
        {"name": "web_search", "description": "Web search"},
        {"name": "web_fetch", "description": "Fetch webpage content"},
    ]

    def __init__(self) -> None:
        self.iter_calls = 0

    async def run(self, user_message, deps):
        if "Classify the following request for runtime policy." in str(user_message):
            return _RunResult(
                json.dumps(
                    {
                        "needs_tool": True,
                        "needs_live_data": True,
                        "needs_private_context": False,
                        "needs_external_system": False,
                        "needs_browser_interaction": False,
                        "needs_grounded_verification": True,
                        "suggested_tool_classes": ["web_search"],
                        "confidence": 0.88,
                        "reason": "Live weather query should use tools first.",
                        "policy": "prefer_tool",
                    }
                )
            )
        return _RunResult("上海明天多云转小雨，14℃到23℃。")

    def iter(self, user_message, deps, message_history):
        self.iter_calls += 1
        raise AssertionError("prefer_tool with strict need should short-circuit to tool-first path")


class _FakeAgentRun:
    def __init__(self, nodes: list[object], all_messages: list[dict[str, Any]]):
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


class _DirectAnswerAgent:
    tools: list[dict[str, str]] = []

    async def run(self, user_message, deps):
        return _RunResult(
            json.dumps(
                {
                    "needs_tool": False,
                    "needs_live_data": False,
                    "needs_private_context": False,
                    "needs_external_system": False,
                    "needs_browser_interaction": False,
                    "needs_grounded_verification": False,
                    "suggested_tool_classes": [],
                    "confidence": 0.91,
                    "reason": "Stable factual question.",
                    "policy": "answer_direct",
                }
            )
        )

    def iter(self, user_message, deps, message_history):
        final_messages = list(message_history) + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": "法国首都是巴黎。"},
        ]
        return _FakeAgentRun([_TextNode("法国首都是巴黎。")], final_messages)


class _MissingCapabilityAgent:
    tools: list[dict[str, str]] = []

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, user_message, deps):
        return _RunResult(
            json.dumps(
                {
                    "needs_tool": True,
                    "needs_live_data": True,
                    "needs_private_context": False,
                    "needs_external_system": False,
                    "needs_browser_interaction": False,
                    "needs_grounded_verification": True,
                    "suggested_tool_classes": ["web_search"],
                    "confidence": 0.95,
                    "reason": "Live verification is required.",
                    "policy": "must_use_tool",
                }
            )
        )


class _ClarifyingFollowUpAgent:
    tools = [
        {"name": "web_search", "description": "Web search"},
        {"name": "web_fetch", "description": "Fetch webpage content"},
    ]

    def __init__(self) -> None:
        self.iter_calls: list[str] = []

    async def run(self, user_message, deps):
        return _RunResult("")

    def iter(self, user_message, deps, message_history):
        self.iter_calls.append(str(user_message))
        if str(user_message) == "上海周日天气":
            final_messages = list(message_history) + [
                {"role": "user", "content": user_message},
                {
                    "role": "assistant",
                    "content": (
                        "我可以帮你查，但需要你确认是这个周日还是下个周日。"
                        "请回复 1) 这个周日 2) 下个周日。"
                    ),
                },
            ]
            return _FakeAgentRun(
                [
                    _TextNode(
                        "我可以帮你查，但需要你确认是这个周日还是下个周日。"
                        "请回复 1) 这个周日 2) 下个周日。"
                    )
                ],
                final_messages,
            )
        raise AssertionError("follow-up reply should short-circuit into controlled tool-first path")


class _SlowFirstNodeRun:
    def __init__(self, all_messages: list[dict[str, Any]], sleep_seconds: float = 9.5):
        self._all_messages = all_messages
        self._sleep_seconds = sleep_seconds

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(self._sleep_seconds)
        raise StopAsyncIteration

    def all_messages(self):
        return self._all_messages


class _SlowFirstNodeAgent:
    tools = [
        {"name": "web_search", "description": "Web search"},
        {"name": "web_fetch", "description": "Fetch webpage content"},
    ]

    async def run(self, user_message, deps):
        if "Classify the following request for runtime policy." in str(user_message):
            return _RunResult(
                json.dumps(
                    {
                        "needs_tool": True,
                        "needs_live_data": True,
                        "needs_private_context": False,
                        "needs_external_system": False,
                        "needs_browser_interaction": False,
                        "needs_grounded_verification": True,
                        "suggested_tool_classes": ["web_search"],
                        "confidence": 0.96,
                        "reason": "Live verification required.",
                        "policy": "must_use_tool",
                    }
                )
            )
        return _RunResult("")

    def iter(self, user_message, deps, message_history):
        final_messages = list(message_history) + [{"role": "user", "content": user_message}]
        return _SlowFirstNodeRun(final_messages)


def _build_client_and_runner(tmp_path, agent, *, enable_model_classifier: bool = False) -> tuple[TestClient, AgentRunner]:
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
    runner = AgentRunner(
        agent=agent,
        session_manager=session_manager,
        session_manager_router=session_router,
        session_queue=SessionQueue(),
        hook_runtime=hook_runtime,
        tool_gate_model_classifier_enabled=enable_model_classifier,
    )
    ctx = APIContext(
        session_manager=session_manager,
        session_queue=SessionQueue(),
        session_manager_router=session_router,
        skill_registry=SkillRegistry(),
        hook_state_store=hook_state_store,
        memory_sink=MemorySink(str(tmp_path)),
        context_sink=ContextSink(hook_state_store),
        hook_runtime=hook_runtime,
        agent_runner=runner,
    )
    set_api_context(ctx)

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), runner


def _build_client(tmp_path, agent, *, enable_model_classifier: bool = False) -> TestClient:
    client, _runner = _build_client_and_runner(
        tmp_path,
        agent,
        enable_model_classifier=enable_model_classifier,
    )
    return client


def _parse_sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    current_event: str | None = None
    current_data: str | None = None
    for line in body.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            current_data = line.removeprefix("data: ")
        elif not line and current_event and current_data:
            events.append((current_event, json.loads(current_data)))
            current_event = None
            current_data = None
    if current_event and current_data:
        events.append((current_event, json.loads(current_data)))
    return events
def test_stable_fact_query_can_answer_directly_via_api(tmp_path) -> None:
    client = _build_client(tmp_path, _DirectAnswerAgent(), enable_model_classifier=True)

    session_resp = client.post("/api/sessions", json={})
    assert session_resp.status_code == 200
    session_key = session_resp.json()["session_key"]

    run_resp = client.post(
        "/api/agent/run",
        json={"session_key": session_key, "message": "法国首都是哪里？", "timeout_seconds": 30},
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    with client.stream("GET", f"/api/agent/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    assert ("assistant", {"text": "法国首都是巴黎。", "is_delta": True}) in events

