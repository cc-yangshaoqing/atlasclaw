# -*- coding: utf-8 -*-
"""E2E-style routing regressions for planner-free runtime behavior."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.atlasclaw.agent.stream import StreamEvent
from app.atlasclaw.api.routes import APIContext, create_router, set_api_context
from app.atlasclaw.session.manager import SessionManager
from app.atlasclaw.session.queue import SessionQueue
from app.atlasclaw.skills.registry import SkillRegistry


pytestmark = pytest.mark.e2e


PENDING_REQUESTS = [
    {"id": "TIC20260316000001", "title": "扩容生产主机", "approver": "一级审批"},
    {"id": "TIC20260313000006", "title": "创建测试 VPC", "approver": "一级审批"},
    {"id": "TIC20260313000004", "title": "开通支持服务", "approver": "二级审批"},
]


class _ScriptedRoutingRunner:
    """Small scripted runner to exercise API/session/SSE boundaries."""

    def __init__(self) -> None:
        self._session_state: dict[str, dict[str, Any]] = {}

    async def run(self, session_key, user_message, deps, timeout_seconds=600, **kwargs):
        state = self._session_state.setdefault(
            session_key,
            {
                "pending_requests": [],
                "last_markdown_path": "",
            },
        )
        message = str(user_message or "").strip()

        yield StreamEvent.lifecycle_start()
        yield StreamEvent.runtime_update("reasoning", "Starting response analysis.")

        if message == "查一个 cmp 所有待审批的申请":
            async for event in self._run_pending_lookup(state):
                yield event
        elif message == "将这些申请写入一个新的PPT":
            async for event in self._run_ppt_follow_up(state):
                yield event
        elif message == "把上面的结果保存成 markdown":
            async for event in self._run_markdown_export(state):
                yield event
        elif message == "我想查下上海周边的骑行公园":
            async for event in self._run_direct_answer():
                yield event
        else:
            yield StreamEvent.assistant_delta(f"Unhandled scripted message: {message}")
            yield StreamEvent.runtime_update("answered", "Final answer ready.")

        yield StreamEvent.lifecycle_end()

    async def _run_pending_lookup(self, state: dict[str, Any]):
        state["pending_requests"] = list(PENDING_REQUESTS)
        selected_ids = ["provider:smartcmp", "tool:smartcmp_list_pending"]
        yield StreamEvent.runtime_update(
            "reasoning",
            "Analyzing request.",
            metadata={
                "phase": "model_request",
                "loop_index": 1,
                "loop_reason": "initial_request",
                "selected_capability_ids": selected_ids,
            },
        )
        yield StreamEvent.runtime_update(
            "waiting_for_tool",
            "Preparing tool execution.",
            metadata={"loop_index": 1, "loop_reason": "initial_request"},
        )
        yield StreamEvent.tool_start("smartcmp_list_pending")
        yield StreamEvent.tool_end(
            "smartcmp_list_pending",
            json.dumps(PENDING_REQUESTS, ensure_ascii=False),
        )
        yield StreamEvent.runtime_update(
            "reasoning",
            "Re-entering model loop with tool evidence.",
            metadata={
                "phase": "model_request",
                "loop_index": 2,
                "loop_reason": "tool_result_continuation",
                "tool_result_count": 1,
                "selected_capability_ids": selected_ids,
            },
        )
        assistant = (
            "当前待审批申请共 3 条："
            "TIC20260316000001 扩容生产主机，"
            "TIC20260313000006 创建测试 VPC，"
            "TIC20260313000004 开通支持服务。"
        )
        yield StreamEvent.assistant_delta(assistant)
        yield StreamEvent.runtime_update("answered", "Final answer ready.")

    async def _run_ppt_follow_up(self, state: dict[str, Any]):
        pending_requests = list(state.get("pending_requests") or [])
        selected_ids = ["skill:powerpoint-pptx-1.0.1"]
        yield StreamEvent.runtime_update(
            "reasoning",
            "Analyzing request.",
            metadata={
                "phase": "model_request",
                "loop_index": 1,
                "loop_reason": "initial_request",
                "selected_capability_ids": selected_ids,
            },
        )
        if pending_requests:
            assistant = (
                "我已经根据上文的 3 条申请整理出了 PPT 内容大纲，"
                "但当前这条测试链路没有实际落盘 .pptx 文件。"
            )
        else:
            assistant = "我没有找到上文中的申请列表，暂时无法整理 PPT 内容。"
        yield StreamEvent.assistant_delta(assistant)
        yield StreamEvent.runtime_update("answered", "Final answer ready.")

    async def _run_markdown_export(self, state: dict[str, Any]):
        pending_requests = list(state.get("pending_requests") or [])
        read_ids = ["tool:read", "tool:write", "capability:file_export"]
        markdown_path = "/workspace/exports/pending-approvals.md"

        yield StreamEvent.runtime_update(
            "reasoning",
            "Analyzing request.",
            metadata={
                "phase": "model_request",
                "loop_index": 1,
                "loop_reason": "initial_request",
                "selected_capability_ids": read_ids,
            },
        )
        yield StreamEvent.runtime_update(
            "waiting_for_tool",
            "Preparing tool execution.",
            metadata={"loop_index": 1, "loop_reason": "initial_request"},
        )
        yield StreamEvent.tool_start("read")
        yield StreamEvent.tool_end(
            "read",
            json.dumps({"pending_requests": pending_requests}, ensure_ascii=False),
        )
        yield StreamEvent.runtime_update(
            "reasoning",
            "Re-entering model loop with tool evidence.",
            metadata={
                "phase": "model_request",
                "loop_index": 2,
                "loop_reason": "tool_result_continuation",
                "tool_result_count": 1,
                "selected_capability_ids": read_ids,
            },
        )
        yield StreamEvent.runtime_update(
            "waiting_for_tool",
            "Preparing tool execution.",
            metadata={"loop_index": 2, "loop_reason": "tool_result_continuation"},
        )
        yield StreamEvent.tool_start("write")
        yield StreamEvent.tool_end(
            "write",
            json.dumps({"file_path": markdown_path}, ensure_ascii=False),
        )
        state["last_markdown_path"] = markdown_path
        yield StreamEvent.runtime_update(
            "reasoning",
            "Re-entering model loop with tool evidence.",
            metadata={
                "phase": "model_request",
                "loop_index": 3,
                "loop_reason": "tool_result_continuation",
                "tool_result_count": 2,
                "selected_capability_ids": read_ids,
            },
        )
        assistant = f"已经把上面的申请保存成 markdown：{markdown_path}"
        yield StreamEvent.assistant_delta(assistant)
        yield StreamEvent.runtime_update("answered", "Final answer ready.")

    async def _run_direct_answer(self):
        selected_ids = ["capability:direct_answer"]
        yield StreamEvent.runtime_update(
            "reasoning",
            "Analyzing request.",
            metadata={
                "phase": "model_request",
                "loop_index": 1,
                "loop_reason": "initial_request",
                "selected_capability_ids": selected_ids,
            },
        )
        assistant = (
            "上海周边可以优先考虑共青森林公园、青西郊野公园、东平国家森林公园这类适合轻松骑行的目的地。"
        )
        yield StreamEvent.assistant_delta(assistant)
        yield StreamEvent.runtime_update("answered", "Final answer ready.")


def _build_client(tmp_path) -> TestClient:
    ctx = APIContext(
        session_manager=SessionManager(agents_dir=str(tmp_path / "agents")),
        session_queue=SessionQueue(),
        skill_registry=SkillRegistry(),
        agent_runner=_ScriptedRoutingRunner(),
    )
    set_api_context(ctx)

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


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


def _run_round(client: TestClient, *, session_key: str, message: str) -> list[tuple[str, dict[str, Any]]]:
    run = client.post(
        "/api/agent/run",
        json={"session_key": session_key, "message": message, "timeout_seconds": 30},
    )
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    with client.stream("GET", f"/api/agent/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        return _parse_sse_events("".join(response.iter_text()))


def _assistant_text(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(payload.get("text", "") for event_name, payload in events if event_name == "assistant")


def _runtime_events(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [payload for event_name, payload in events if event_name == "runtime"]


def _tool_events(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [payload for event_name, payload in events if event_name == "tool"]


def test_follow_up_ppt_request_uses_context_without_requerying_provider(tmp_path) -> None:
    client = _build_client(tmp_path)
    session = client.post("/api/sessions", json={})
    assert session.status_code == 200
    session_key = session.json()["session_key"]

    first_events = _run_round(client, session_key=session_key, message="查一个 cmp 所有待审批的申请")
    assert "TIC20260316000001" in _assistant_text(first_events)

    second_events = _run_round(client, session_key=session_key, message="将这些申请写入一个新的PPT")
    second_runtime = _runtime_events(second_events)
    second_tools = _tool_events(second_events)

    assert not any(str(item.get("tool", "")).startswith("smartcmp_") for item in second_tools)
    assert not any("Planning tool routing." in str(item.get("message", "")) for item in second_runtime)
    reasoning_items = [
        item for item in second_runtime if item.get("state") == "reasoning" and "loop_index" in item
    ]
    assert reasoning_items[0]["loop_index"] == 1
    assert reasoning_items[0]["loop_reason"] == "initial_request"
    assert reasoning_items[0]["selected_capability_ids"] == ["skill:powerpoint-pptx-1.0.1"]
    assert "上文的 3 条申请" in _assistant_text(second_events)
    assert ".pptx 文件" in _assistant_text(second_events)


def test_general_public_recommendation_can_answer_directly_without_tool_events(tmp_path) -> None:
    client = _build_client(tmp_path)
    session = client.post("/api/sessions", json={})
    assert session.status_code == 200
    session_key = session.json()["session_key"]

    events = _run_round(client, session_key=session_key, message="我想查下上海周边的骑行公园")
    runtime_items = _runtime_events(events)

    assert _tool_events(events) == []
    reasoning_items = [
        item for item in runtime_items if item.get("state") == "reasoning" and "loop_index" in item
    ]
    assert reasoning_items[0]["loop_reason"] == "initial_request"
    assert runtime_items[-1]["state"] == "answered"
    assert "共青森林公园" in _assistant_text(events)


def test_markdown_export_round_streams_every_llm_reentry_explicitly(tmp_path) -> None:
    client = _build_client(tmp_path)
    session = client.post("/api/sessions", json={})
    assert session.status_code == 200
    session_key = session.json()["session_key"]

    _run_round(client, session_key=session_key, message="查一个 cmp 所有待审批的申请")
    export_events = _run_round(client, session_key=session_key, message="把上面的结果保存成 markdown")
    runtime_items = _runtime_events(export_events)
    tool_items = _tool_events(export_events)

    reasoning_items = [
        item for item in runtime_items if item.get("state") == "reasoning" and "loop_index" in item
    ]
    assert [item["loop_index"] for item in reasoning_items] == [1, 2, 3]
    assert [item["loop_reason"] for item in reasoning_items] == [
        "initial_request",
        "tool_result_continuation",
        "tool_result_continuation",
    ]
    assert all(
        item["selected_capability_ids"] == ["tool:read", "tool:write", "capability:file_export"]
        for item in reasoning_items
    )
    assert [item["tool"] for item in tool_items if item["phase"] == "start"] == ["read", "write"]
    assert _assistant_text(export_events).endswith("/workspace/exports/pending-approvals.md")
