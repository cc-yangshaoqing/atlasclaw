# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

import pytest

from app.atlasclaw.agent.runner_tool.runner_tool_gate_model import RunnerToolGateModelMixin
from app.atlasclaw.agent.runner_tool.runner_execution_prepare import RunnerExecutionPreparePhaseMixin
from app.atlasclaw.agent.runner_tool.runner_llm_routing import build_llm_first_intent_plan
from app.atlasclaw.agent.runner_tool.runner_tool_gate_routing import RunnerToolGateRoutingMixin
from app.atlasclaw.agent.runner_tool.runner_tool_projection import project_minimal_toolset
from app.atlasclaw.agent.tool_gate import CapabilityMatcher
from app.atlasclaw.agent.tool_gate_models import (
    ToolGateDecision,
    ToolIntentAction,
    ToolIntentPlan,
    ToolPolicyMode,
)


class _GateRunner(RunnerToolGateModelMixin, RunnerToolGateRoutingMixin):
    TOOL_GATE_SHORT_CIRCUIT_MIN_CONFIDENCE = 0.55
    TOOL_GATE_MUST_USE_MIN_CONFIDENCE = 0.85
    TOOL_HINT_RANKER_MIN_METADATA_CONFIDENCE = 0.30


class _PrepareRunner(RunnerExecutionPreparePhaseMixin):
    pass


class _HangingAgent:
    async def run(self, *args, **kwargs):
        await asyncio.sleep(3600)


def test_normalize_external_intent_does_not_force_must_use_tool() -> None:
    runner = _GateRunner()
    decision = ToolGateDecision(
        needs_tool=True,
        needs_external_system=True,
        suggested_tool_classes=["provider:smartcmp"],
        confidence=0.40,
        reason="external system request",
        policy=ToolPolicyMode.ANSWER_DIRECT,
    )

    normalized = runner._normalize_tool_gate_decision(decision)

    assert normalized.policy is ToolPolicyMode.PREFER_TOOL
    assert normalized.needs_external_system is True
    assert normalized.needs_tool is True


def test_align_external_system_intent_keeps_prefer_tool_policy() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "cmp_list_pending",
            "description": "List CMP pending requests",
            "capability_class": "provider:smartcmp",
            "provider_type": "smartcmp",
        }
    ]
    initial_decision = ToolGateDecision(
        needs_tool=True,
        needs_external_system=True,
        suggested_tool_classes=[],
        confidence=0.30,
        reason="external request",
        policy=ToolPolicyMode.ANSWER_DIRECT,
    )
    initial_match = CapabilityMatcher(available_tools=available_tools).match(["provider:smartcmp"])

    aligned_decision, _ = runner._align_external_system_intent(
        decision=initial_decision,
        match_result=initial_match,
        available_tools=available_tools,
        user_message="查下CMP待审批",
        recent_history=[],
        deps=None,
    )

    assert aligned_decision.policy is ToolPolicyMode.PREFER_TOOL
    assert aligned_decision.suggested_tool_classes == ["provider:smartcmp"]


def test_normalize_live_data_only_intent_keeps_answer_direct_without_tool_hints() -> None:
    runner = _GateRunner()
    decision = ToolGateDecision(
        needs_live_data=True,
        reason="public info request",
        policy=ToolPolicyMode.ANSWER_DIRECT,
    )

    normalized = runner._normalize_tool_gate_decision(decision)

    assert normalized.policy is ToolPolicyMode.ANSWER_DIRECT
    assert normalized.needs_external_system is False


def test_tool_gate_classifier_prompt_does_not_force_public_realtime_queries_into_tools() -> None:
    runner = _GateRunner()

    prompt = runner._build_tool_gate_classifier_prompt(
        [
            {
                "name": "web_search",
                "description": "Search the public web",
                "capability_class": "web_search",
            }
        ]
    )

    assert "Requests about current or near-future changing facts must prefer tool-backed verification" not in prompt
    assert "Use web_search/web_fetch for public web real-time verification" not in prompt
    assert "Use answer_direct when the request can be handled from model knowledge" in prompt


def test_tool_intent_planner_prompt_treats_generic_web_tools_as_fallback_not_clear_match() -> None:
    runner = _GateRunner()

    prompt = runner._build_tool_intent_plan_prompt(
        available_tools=[
            {
                "name": "web_search",
                "description": "Search the public web",
                "capability_class": "web_search",
                "group_ids": ["group:web"],
            }
        ],
        provider_hint_docs=[],
        skill_hint_docs=[],
        tool_hint_docs=[],
    )

    assert "Generic fallback tools such as web_search or web_fetch do not count as a strong capability match by themselves." in prompt
    assert "For public recommendations, broad Q&A, and general knowledge requests, prefer `direct_answer`" in prompt


def test_metadata_fallback_accepts_single_provider_tool_consensus_below_threshold() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "smartcmp_list_services",
            "description": "List SmartCMP service catalogs",
            "capability_class": "provider:smartcmp",
            "provider_type": "smartcmp",
        },
        {
            "name": "smartcmp_get_request_detail",
            "description": "Get SmartCMP request detail",
            "capability_class": "provider:smartcmp",
            "provider_type": "smartcmp",
        },
    ]

    plan = runner._build_metadata_fallback_tool_intent_plan(
        metadata_candidates={
            "confidence": 0.08,
            "preferred_provider_types": ["smartcmp"],
            "preferred_capability_classes": ["provider:smartcmp"],
            "preferred_tool_names": [
                "smartcmp_list_services",
                "smartcmp_get_request_detail",
            ],
            "reason": "metadata_recall_matched",
        },
        available_tools=available_tools,
    )

    assert plan is not None
    assert plan.action.value == "use_tools"
    assert plan.target_provider_types == ["smartcmp"]
    assert plan.target_tool_names == ["smartcmp_list_services", "smartcmp_get_request_detail"]


def test_projected_toolset_short_circuit_uses_single_tool_only_ok() -> None:
    runner = _GateRunner()

    plan = runner._build_projected_toolset_short_circuit_intent_plan(
        planner_available_tools=[
            {
                "name": "openmeteo_weather",
                "description": "Get weather forecast",
                "capability_class": "weather",
                "group_ids": ["group:web"],
                "result_mode": "tool_only_ok",
            },
            {
                "name": "select_provider_instance",
                "description": "Select provider instance",
                "capability_class": "session",
                "group_ids": ["group:atlasclaw"],
            },
        ]
    )

    assert plan is not None
    assert plan.action is ToolIntentAction.USE_TOOLS
    assert plan.target_tool_names == ["openmeteo_weather"]
    assert plan.target_capability_classes == ["weather"]
    assert plan.target_group_ids == ["group:web"]


def test_projected_toolset_short_circuit_skips_non_tool_only_result_mode() -> None:
    runner = _GateRunner()

    plan = runner._build_projected_toolset_short_circuit_intent_plan(
        planner_available_tools=[
            {
                "name": "smartcmp_approve",
                "description": "Approve SmartCMP request",
                "capability_class": "provider:smartcmp",
                "provider_type": "smartcmp",
                "group_ids": ["group:cmp", "group:approval"],
                "result_mode": "llm",
            }
        ]
    )

    assert plan is None


def test_project_minimal_toolset_keeps_explicit_target_tool_even_with_provider_target() -> None:
    intent_plan = ToolIntentPlan(
        action=ToolIntentAction.USE_TOOLS,
        target_provider_types=["smartcmp"],
        target_tool_names=["atlasclaw_catalog_query"],
        target_capability_classes=["atlasclaw_catalog"],
        reason="platform catalog query scoped to SmartCMP",
    )

    projected, trace = project_minimal_toolset(
        allowed_tools=[
            {
                "name": "atlasclaw_catalog_query",
                "description": "Query AtlasClaw runtime catalog",
                "capability_class": "atlasclaw_catalog",
                "group_ids": ["group:catalog", "group:atlasclaw"],
                "result_mode": "tool_only_ok",
            },
            {
                "name": "smartcmp_list_pending",
                "description": "List SmartCMP pending approvals",
                "provider_type": "smartcmp",
                "capability_class": "provider:smartcmp",
                "group_ids": ["group:cmp", "group:smartcmp"],
            },
            {
                "name": "select_provider_instance",
                "description": "Select provider instance",
                "capability_class": "provider:generic",
                "group_ids": ["group:providers", "group:atlasclaw"],
            },
        ],
        intent_plan=intent_plan,
    )

    projected_names = {item["name"] for item in projected}
    assert "atlasclaw_catalog_query" in projected_names
    assert "smartcmp_list_pending" not in projected_names
    assert trace["reason"] == "projection_applied"


def test_align_tool_intent_plan_with_metadata_does_not_merge_unrelated_provider_hints() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "openmeteo_weather",
            "description": "Get weather forecast",
            "capability_class": "weather",
            "group_ids": ["group:web"],
        },
        {
            "name": "smartcmp_list_pending",
            "description": "List SmartCMP pending approvals",
            "capability_class": "provider:smartcmp",
            "provider_type": "smartcmp",
        },
    ]
    plan = ToolIntentPlan(
        action=ToolIntentAction.USE_TOOLS,
        target_capability_classes=["weather"],
        target_tool_names=["openmeteo_weather"],
        reason="weather request",
    )

    aligned = runner._align_tool_intent_plan_with_metadata(
        plan=plan,
        metadata_candidates={
            "confidence": 0.82,
            "preferred_provider_types": ["smartcmp"],
            "preferred_capability_classes": ["provider:smartcmp"],
            "preferred_tool_names": ["smartcmp_list_pending"],
            "reason": "metadata_recall_matched",
        },
        available_tools=available_tools,
    )

    assert aligned.target_provider_types == []
    assert aligned.target_capability_classes == ["weather"]
    assert aligned.target_tool_names == ["openmeteo_weather"]


def test_metadata_recall_prefers_higher_scored_catalog_tool_over_provider_bundle() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "atlasclaw_catalog_query",
            "description": "Query AtlasClaw runtime catalogs for available providers, skills, tools, and groups",
            "capability_class": "atlasclaw_catalog",
            "group_ids": ["group:catalog", "group:atlasclaw"],
            "aliases": ["catalog", "skills catalog", "tool catalog", "provider catalog", "runtime catalog"],
            "keywords": ["available skills", "available tools", "providers", "catalog", "capabilities"],
            "use_when": ["User asks which skills or tools are available for a specific provider"],
            "priority": 40,
        },
        {
            "name": "smartcmp_list_pending",
            "description": "List SmartCMP pending approvals",
            "provider_type": "smartcmp",
            "capability_class": "provider:smartcmp",
            "group_ids": ["group:cmp", "group:smartcmp"],
            "priority": 100,
        },
        {
            "name": "smartcmp_list_services",
            "description": "List SmartCMP service catalogs",
            "provider_type": "smartcmp",
            "capability_class": "provider:smartcmp",
            "group_ids": ["group:cmp", "group:smartcmp"],
            "priority": 100,
        },
    ]
    provider_hint_docs = [
        {
            "hint_id": "provider:smartcmp",
            "provider_type": "smartcmp",
            "display_name": "SmartCMP",
            "aliases": ["cmp"],
            "keywords": ["approval", "service catalog", "cmp"],
            "capabilities": ["provider:smartcmp"],
            "use_when": ["Query SmartCMP requests or service catalogs"],
            "avoid_when": [],
            "tool_names": ["smartcmp_list_pending", "smartcmp_list_services"],
            "group_ids": ["group:cmp", "group:smartcmp"],
            "capability_classes": ["provider:smartcmp"],
            "priority": 80,
            "hint_text": "SmartCMP enterprise service management cmp approval service catalog",
        }
    ]
    tool_hint_docs = runner._build_tool_hint_docs(available_tools=available_tools)

    metadata = runner._recall_provider_skill_candidates_from_metadata(
        user_message="CMP现在有哪些skills可以使用",
        recent_history=[],
        used_follow_up_context=False,
        available_tools=available_tools,
        provider_hint_docs=provider_hint_docs,
        skill_hint_docs=[],
        tool_hint_docs=tool_hint_docs,
        top_k_provider=2,
        top_k_skill=3,
    )

    assert metadata["tool_candidates"][0]["tool_name"] == "atlasclaw_catalog_query"
    assert metadata["preferred_tool_names"][0] == "atlasclaw_catalog_query"


def test_metadata_fallback_prefers_dominant_tool_candidate_over_broad_provider_bundle() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "atlasclaw_catalog_query",
            "description": "Query AtlasClaw runtime catalogs",
            "capability_class": "atlasclaw_catalog",
            "group_ids": ["group:catalog", "group:atlasclaw"],
            "result_mode": "tool_only_ok",
            "priority": 40,
        },
        {
            "name": "smartcmp_list_pending",
            "description": "List SmartCMP pending approvals",
            "provider_type": "smartcmp",
            "capability_class": "provider:smartcmp",
            "group_ids": ["group:cmp", "group:smartcmp"],
            "priority": 100,
        },
        {
            "name": "smartcmp_list_services",
            "description": "List SmartCMP service catalogs",
            "provider_type": "smartcmp",
            "capability_class": "provider:smartcmp",
            "group_ids": ["group:cmp", "group:smartcmp"],
            "priority": 100,
        },
    ]

    plan = runner._build_metadata_fallback_tool_intent_plan(
        metadata_candidates={
            "confidence": 0.86,
            "preferred_provider_types": ["smartcmp"],
            "preferred_group_ids": ["group:cmp", "group:catalog"],
            "preferred_capability_classes": ["provider:smartcmp", "atlasclaw_catalog"],
            "preferred_tool_names": [
                "atlasclaw_catalog_query",
                "smartcmp_list_pending",
                "smartcmp_list_services",
            ],
            "tool_candidates": [
                {
                    "hint_id": "tool:atlasclaw_catalog_query",
                    "tool_name": "atlasclaw_catalog_query",
                    "score": 12,
                    "has_strong_anchor": True,
                    "tool_names": ["atlasclaw_catalog_query"],
                    "group_ids": ["group:catalog", "group:atlasclaw"],
                    "capability_classes": ["atlasclaw_catalog"],
                },
                {
                    "hint_id": "tool:smartcmp_list_pending",
                    "tool_name": "smartcmp_list_pending",
                    "score": 4,
                    "has_strong_anchor": False,
                    "tool_names": ["smartcmp_list_pending"],
                    "group_ids": ["group:cmp", "group:smartcmp"],
                    "capability_classes": ["provider:smartcmp"],
                },
            ],
            "reason": "metadata_recall_matched",
        },
        available_tools=available_tools,
    )

    assert plan is not None
    assert plan.target_tool_names == ["atlasclaw_catalog_query"]
    assert plan.target_capability_classes == ["atlasclaw_catalog"]
    assert plan.target_provider_types == []


def test_align_tool_intent_plan_with_metadata_prefers_explicit_single_tool_fallback() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "atlasclaw_catalog_query",
            "description": "Query AtlasClaw runtime catalogs",
            "capability_class": "atlasclaw_catalog",
            "group_ids": ["group:catalog", "group:atlasclaw"],
            "result_mode": "tool_only_ok",
        },
        {
            "name": "smartcmp_list_pending",
            "description": "List SmartCMP pending approvals",
            "provider_type": "smartcmp",
            "capability_class": "provider:smartcmp",
            "group_ids": ["group:cmp", "group:smartcmp"],
        },
    ]
    plan = ToolIntentPlan(
        action=ToolIntentAction.USE_TOOLS,
        target_provider_types=["smartcmp"],
        target_capability_classes=["provider:smartcmp"],
        reason="planner selected provider family",
    )

    aligned = runner._align_tool_intent_plan_with_metadata(
        plan=plan,
        metadata_candidates={
            "confidence": 0.88,
            "preferred_provider_types": ["smartcmp"],
            "preferred_group_ids": ["group:catalog"],
            "preferred_capability_classes": ["atlasclaw_catalog"],
            "preferred_tool_names": ["atlasclaw_catalog_query"],
            "tool_candidates": [
                {
                    "hint_id": "tool:atlasclaw_catalog_query",
                    "tool_name": "atlasclaw_catalog_query",
                    "score": 10,
                    "has_strong_anchor": True,
                    "tool_names": ["atlasclaw_catalog_query"],
                    "group_ids": ["group:catalog", "group:atlasclaw"],
                    "capability_classes": ["atlasclaw_catalog"],
                }
            ],
            "reason": "metadata_recall_matched",
        },
        available_tools=available_tools,
    )

    assert aligned.target_tool_names == ["atlasclaw_catalog_query"]
    assert aligned.target_capability_classes == ["atlasclaw_catalog"]


def test_classifier_history_ignores_recent_history_for_complete_new_request() -> None:
    runner = _GateRunner()

    history = runner._build_classifier_history(
        user_message="明天上海天气如何",
        recent_history=[
            {"role": "user", "content": "查下CMP 里目前所有待审批"},
            {"role": "assistant", "content": "我来帮你查。"},
        ],
        used_follow_up_context=False,
    )

    assert history == []


def test_resolve_contextual_tool_request_keeps_rich_identifier_query_self_contained() -> None:
    runner = _GateRunner()

    resolved, used_follow_up_context = runner._resolve_contextual_tool_request(
        user_message="我要看下TIC20260316000001的详情",
        recent_history=[
            {"role": "user", "content": "查下CMP 里目前所有待审批"},
            {"role": "assistant", "content": "好的，我帮你列出来。"},
        ],
    )

    assert resolved == "我要看下TIC20260316000001的详情"
    assert used_follow_up_context is False


def test_metadata_recall_ignores_history_when_not_follow_up() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "openmeteo_weather",
            "description": "Get weather forecast",
            "capability_class": "weather",
            "group_ids": ["group:web"],
        },
        {
            "name": "smartcmp_list_pending",
            "description": "List SmartCMP pending approvals",
            "capability_class": "provider:smartcmp",
            "provider_type": "smartcmp",
            "group_ids": ["group:cmp"],
        },
    ]
    provider_hint_docs = [
        {
            "hint_id": "provider:smartcmp",
            "provider_type": "smartcmp",
            "display_name": "SmartCMP",
            "description": "List SmartCMP approvals",
            "aliases": ["cmp"],
            "keywords": ["cmp", "approval", "pending"],
            "capabilities": [],
            "use_when": [],
            "avoid_when": [],
            "tool_names": ["smartcmp_list_pending"],
            "group_ids": ["group:cmp"],
            "capability_classes": ["provider:smartcmp"],
            "hint_text": "keywords: cmp approval pending workflow request",
            "priority": 50,
        }
    ]
    skill_hint_docs = [
        {
            "hint_id": "skill:weather",
            "skill_name": "weather",
            "qualified_skill_name": "builtin:weather",
            "provider_type": "",
            "display_name": "weather",
            "description": "Get weather forecast",
            "aliases": ["builtin:weather"],
            "keywords": ["天气", "预报", "明天", "上海", "温度", "下雨"],
            "capabilities": [],
            "use_when": [],
            "avoid_when": [],
            "tool_names": ["openmeteo_weather"],
            "group_ids": ["group:web"],
            "capability_classes": ["weather"],
            "hint_text": "keywords: 天气 预报 明天 上海 温度 下雨",
            "priority": 20,
        }
    ]

    recalled = runner._recall_provider_skill_candidates_from_metadata(
        user_message="明天上海天气如何",
        recent_history=[
            {"role": "user", "content": "查下CMP 里目前所有待审批"},
            {"role": "assistant", "content": "好的，我帮你列出来。"},
        ],
        used_follow_up_context=False,
        available_tools=available_tools,
        provider_hint_docs=provider_hint_docs,
        skill_hint_docs=skill_hint_docs,
        tool_hint_docs=[],
        top_k_provider=2,
        top_k_skill=2,
    )

    assert recalled["preferred_provider_types"] == []
    assert "weather" in recalled["preferred_capability_classes"]
    assert recalled["preferred_tool_names"] == ["openmeteo_weather"]


def test_metadata_recall_requires_strong_provider_anchor_for_public_query() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "web_search",
            "description": "Search the public web",
            "capability_class": "web_search",
            "group_ids": ["group:web"],
        },
        {
            "name": "smartcmp_list_services",
            "description": "List SmartCMP services",
            "capability_class": "provider:smartcmp",
            "provider_type": "smartcmp",
            "group_ids": ["group:cmp"],
        },
    ]
    provider_hint_docs = [
        {
            "hint_id": "provider:smartcmp",
            "provider_type": "smartcmp",
            "display_name": "SmartCMP",
            "description": "List SmartCMP services",
            "aliases": ["cmp"],
            "keywords": ["cmp", "approval", "request"],
            "capabilities": [],
            "use_when": ["查看待审批和服务目录"],
            "avoid_when": [],
            "tool_names": ["smartcmp_list_services"],
            "group_ids": ["group:cmp"],
            "capability_classes": ["provider:smartcmp"],
            "hint_text": "description: 查看服务目录和请求详情 | use_when: 查看待审批和服务目录",
            "priority": 50,
        }
    ]

    recalled = runner._recall_provider_skill_candidates_from_metadata(
        user_message="查看上海周边有哪些自行车骑行公园",
        recent_history=[],
        used_follow_up_context=False,
        available_tools=available_tools,
        provider_hint_docs=provider_hint_docs,
        skill_hint_docs=[],
        tool_hint_docs=[],
        top_k_provider=2,
        top_k_skill=2,
    )

    assert recalled["preferred_provider_types"] == []
    assert recalled["preferred_tool_names"] == []


def test_tool_hint_docs_support_weather_metadata_recall() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "openmeteo_weather",
            "description": "Get current and forecast weather via Open-Meteo APIs",
            "source": "builtin",
            "capability_class": "weather",
            "group_ids": ["group:web"],
            "aliases": ["weather", "forecast", "openmeteo"],
            "keywords": ["weather", "forecast", "temperature", "rain", "wind", "天气", "预报", "气温", "降雨"],
            "use_when": ["User asks for current or forecast weather conditions for a place and date"],
            "avoid_when": [],
            "priority": 100,
        }
    ]

    builtin_docs = runner._build_tool_hint_docs(available_tools=available_tools)
    recalled = runner._recall_provider_skill_candidates_from_metadata(
        user_message="明天上海天气如何",
        recent_history=[],
        used_follow_up_context=False,
        available_tools=available_tools,
        provider_hint_docs=[],
        skill_hint_docs=[],
        tool_hint_docs=builtin_docs,
        top_k_provider=2,
        top_k_skill=2,
    )

    assert "weather" in recalled["preferred_capability_classes"]
    assert recalled["preferred_tool_names"] == ["openmeteo_weather"]
    assert recalled["confidence"] > 0.0


def test_tool_hint_docs_include_provider_tools() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "smartcmp_get_request_detail",
            "description": "Get CMP request detail by identifier",
            "source": "provider",
            "provider_type": "smartcmp",
            "group_ids": ["group:cmp"],
            "capability_class": "provider:smartcmp",
            "keywords": ["detail", "request detail", "workflow"],
            "use_when": ["User asks for CMP request detail"],
            "avoid_when": [],
        }
    ]

    docs = runner._build_tool_hint_docs(available_tools=available_tools)

    assert docs == [
        {
            "hint_id": "tool:smartcmp_get_request_detail",
            "hint_type": "tool",
            "tool_name": "smartcmp_get_request_detail",
            "provider_type": "smartcmp",
            "display_name": "smartcmp_get_request_detail",
            "description": "Get CMP request detail by identifier",
            "aliases": [],
            "keywords": ["detail", "request detail", "workflow"],
            "capabilities": ["provider:smartcmp"],
            "use_when": ["User asks for CMP request detail"],
            "avoid_when": [],
            "tool_names": ["smartcmp_get_request_detail"],
            "group_ids": ["group:cmp"],
            "capability_classes": ["provider:smartcmp"],
            "hint_text": (
                "name: smartcmp_get_request_detail | description: Get CMP request detail by "
                "identifier | keywords: detail; request detail; workflow | capabilities: "
                "provider:smartcmp | use_when: User asks for CMP request detail"
            ),
            "priority": 100,
        }
    ]


def test_tool_hint_docs_support_provider_metadata_recall() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "smartcmp_get_request_detail",
            "description": "Get CMP request detail by identifier",
            "source": "provider",
            "provider_type": "smartcmp",
            "group_ids": ["group:cmp", "group:request"],
            "capability_class": "provider:smartcmp",
            "aliases": ["cmp request detail", "工单详情"],
            "keywords": ["cmp", "request detail", "workflow", "详情", "工单"],
            "use_when": ["User asks for a CMP request detail page", "User asks for 工单详情"],
            "avoid_when": [],
        }
    ]

    tool_docs = runner._build_tool_hint_docs(available_tools=available_tools)
    recalled = runner._recall_provider_skill_candidates_from_metadata(
        user_message="我要看下TIC20260316000001的详情",
        recent_history=[],
        used_follow_up_context=False,
        available_tools=available_tools,
        provider_hint_docs=[],
        skill_hint_docs=[],
        tool_hint_docs=tool_docs,
        top_k_provider=2,
        top_k_skill=2,
    )

    assert recalled["preferred_provider_types"] == ["smartcmp"]
    assert recalled["preferred_capability_classes"] == ["provider:smartcmp"]
    assert recalled["preferred_tool_names"] == ["smartcmp_get_request_detail"]


def test_metadata_fallback_prefers_local_write_tool_over_generic_provider_create_hints() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "write",
            "description": "Write file content",
            "source": "builtin",
            "group_ids": ["group:fs", "group:atlasclaw"],
            "capability_class": "fs_write",
            "aliases": ["write file", "create file", "save file", "create text file"],
            "keywords": ["write", "create", "file", "save", "content", "overwrite"],
            "use_when": [
                "User asks to create a local file or write text content to a file",
            ],
            "avoid_when": [],
            "result_mode": "tool_only_ok",
        },
        {
            "name": "smartcmp_submit_request",
            "description": "Submit SmartCMP request",
            "source": "provider",
            "provider_type": "smartcmp",
            "group_ids": ["group:cmp", "group:request"],
            "capability_class": "provider:smartcmp",
            "aliases": ["cmp request submit"],
            "keywords": ["cmp", "request", "submit", "create"],
            "use_when": ["User asks to create or submit a CMP request"],
            "avoid_when": [],
        },
        {
            "name": "jira_issue_create",
            "description": "Create Jira issue",
            "source": "provider",
            "provider_type": "jira",
            "group_ids": ["group:jira", "group:issue"],
            "capability_class": "provider:jira",
            "aliases": ["create jira issue"],
            "keywords": ["jira", "issue", "ticket", "create"],
            "use_when": ["User asks to create a Jira issue"],
            "avoid_when": [],
        },
    ]

    provider_hint_docs = [
        {
            "hint_id": "provider:smartcmp",
            "provider_type": "smartcmp",
            "display_name": "SmartCMP",
            "description": "Manage SmartCMP requests and services",
            "aliases": ["cmp"],
            "keywords": ["cmp", "request", "submit", "create"],
            "capabilities": ["provider:smartcmp"],
            "use_when": ["User asks to create or submit a CMP request"],
            "avoid_when": [],
            "tool_names": ["smartcmp_submit_request"],
            "group_ids": ["group:cmp", "group:request"],
            "capability_classes": ["provider:smartcmp"],
            "hint_text": "description: Manage SmartCMP requests and services | use_when: User asks to create or submit a CMP request",
            "priority": 50,
        },
        {
            "hint_id": "provider:jira",
            "provider_type": "jira",
            "display_name": "Jira",
            "description": "Manage Jira issues",
            "aliases": ["jira"],
            "keywords": ["jira", "issue", "ticket", "create"],
            "capabilities": ["provider:jira"],
            "use_when": ["User asks to create a Jira issue"],
            "avoid_when": [],
            "tool_names": ["jira_issue_create"],
            "group_ids": ["group:jira", "group:issue"],
            "capability_classes": ["provider:jira"],
            "hint_text": "description: Manage Jira issues | use_when: User asks to create a Jira issue",
            "priority": 50,
        },
    ]
    tool_hint_docs = runner._build_tool_hint_docs(available_tools=available_tools)
    metadata = runner._recall_provider_skill_candidates_from_metadata(
        user_message='create a file, which name is "test1.txt" and content is "hello ac"',
        recent_history=[
            {"role": "user", "content": "CMP里面有多少待审批的"},
            {"role": "assistant", "content": "我帮你列出来。"},
        ],
        used_follow_up_context=False,
        available_tools=available_tools,
        provider_hint_docs=provider_hint_docs,
        skill_hint_docs=[],
        tool_hint_docs=tool_hint_docs,
        top_k_provider=2,
        top_k_skill=2,
    )
    plan = runner._build_metadata_fallback_tool_intent_plan(
        metadata_candidates=metadata,
        available_tools=available_tools,
    )

    assert plan is not None
    assert plan.action is ToolIntentAction.USE_TOOLS
    assert plan.target_tool_names == ["write"]
    assert plan.target_provider_types == []
    assert plan.target_capability_classes == ["fs_write"]


def test_metadata_fallback_builds_weather_plan_from_builtin_tool_candidates() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "openmeteo_weather",
            "description": "Get current and forecast weather via Open-Meteo APIs",
            "source": "builtin",
            "capability_class": "weather",
            "group_ids": ["group:web"],
        }
    ]

    plan = runner._build_metadata_fallback_tool_intent_plan(
        metadata_candidates={
            "confidence": 0.42,
            "preferred_provider_types": [],
            "preferred_capability_classes": ["weather"],
            "preferred_tool_names": ["openmeteo_weather"],
            "reason": "metadata_recall_matched_builtin_weather",
        },
        available_tools=available_tools,
    )

    assert plan is not None
    assert plan.action.value == "use_tools"
    assert plan.target_capability_classes == ["weather"]
    assert plan.target_tool_names == ["openmeteo_weather"]


def test_metadata_fallback_accepts_single_builtin_tool_consensus_below_threshold() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "openmeteo_weather",
            "description": "Get current and forecast weather via Open-Meteo APIs",
            "source": "builtin",
            "capability_class": "weather",
            "group_ids": ["group:web"],
        },
        {
            "name": "web_search",
            "description": "Search the public web",
            "source": "builtin",
            "capability_class": "web_search",
            "group_ids": ["group:web"],
        },
    ]

    plan = runner._build_metadata_fallback_tool_intent_plan(
        metadata_candidates={
            "confidence": 0.04,
            "preferred_provider_types": [],
            "preferred_capability_classes": ["weather"],
            "preferred_tool_names": ["openmeteo_weather"],
            "builtin_tool_candidates": [
                {
                    "hint_id": "builtin:openmeteo_weather",
                    "tool_name": "openmeteo_weather",
                    "score": 7,
                    "has_strong_anchor": True,
                    "tool_names": ["openmeteo_weather"],
                    "group_ids": ["group:web"],
                    "capability_classes": ["weather"],
                }
            ],
            "reason": "metadata_recall_single_builtin_tool",
        },
        available_tools=available_tools,
    )

    assert plan is not None
    assert plan.action.value == "use_tools"
    assert plan.target_capability_classes == ["weather"]
    assert plan.target_tool_names == ["openmeteo_weather"]


def test_metadata_fallback_accepts_single_tool_consensus_from_tool_candidates() -> None:
    runner = _GateRunner()
    available_tools = [
        {
            "name": "openmeteo_weather",
            "description": "Get current and forecast weather via Open-Meteo APIs",
            "source": "builtin",
            "capability_class": "weather",
            "group_ids": ["group:web"],
        },
        {
            "name": "web_search",
            "description": "Search the public web",
            "source": "builtin",
            "capability_class": "web_search",
            "group_ids": ["group:web"],
        },
    ]

    plan = runner._build_metadata_fallback_tool_intent_plan(
        metadata_candidates={
            "confidence": 0.04,
            "preferred_provider_types": [],
            "preferred_capability_classes": ["weather"],
            "preferred_tool_names": ["openmeteo_weather"],
            "tool_candidates": [
                {
                    "hint_id": "tool:openmeteo_weather",
                    "tool_name": "openmeteo_weather",
                    "score": 7,
                    "has_strong_anchor": True,
                    "tool_names": ["openmeteo_weather"],
                    "group_ids": ["group:web"],
                    "capability_classes": ["weather"],
                }
            ],
            "reason": "metadata_recall_single_tool",
        },
        available_tools=available_tools,
    )

    assert plan is not None
    assert plan.action.value == "use_tools"
    assert plan.target_capability_classes == ["weather"]
    assert plan.target_tool_names == ["openmeteo_weather"]


@pytest.mark.asyncio
async def test_plan_tool_intent_with_model_times_out_instead_of_hanging() -> None:
    runner = _GateRunner()
    runner.TOOL_GATE_MODEL_TIMEOUT_SECONDS = 0.01

    plan = await asyncio.wait_for(
        runner._plan_tool_intent_with_model(
            agent=_HangingAgent(),
            deps=type("Deps", (), {"extra": {}})(),
            user_message="我想查下上海周边的骑行公园",
            recent_history=[],
            available_tools=[
                {
                    "name": "web_search",
                    "description": "Search the public web",
                    "capability_class": "web_search",
                    "group_ids": ["group:web"],
                }
            ],
            provider_hint_docs=[],
            skill_hint_docs=[],
            tool_hint_docs=[],
        ),
        timeout=1.0,
    )

    assert plan is None


def test_runtime_history_for_tool_turns_keeps_recent_context_even_without_follow_up_flag() -> None:
    history = _PrepareRunner._build_runtime_message_history_for_turn(
        session_message_history=[
            {"role": "user", "content": "查一个 cmp 所有待审批的申请"},
            {"role": "assistant", "content": "我已经列出了 3 条待审批申请。"},
        ],
        used_follow_up_context=False,
        intent_plan=ToolIntentPlan(
            action=ToolIntentAction.USE_TOOLS,
            target_provider_types=["smartcmp"],
            reason="legacy tool turn",
        ),
    )

    assert history == [
        {"role": "user", "content": "查一个 cmp 所有待审批的申请"},
        {"role": "assistant", "content": "我已经列出了 3 条待审批申请。"},
    ]


def test_llm_first_intent_plan_keeps_strong_provider_match_on_main_path() -> None:
    plan = build_llm_first_intent_plan(
        user_message="查一个 cmp 所有待审批的申请",
        metadata_plan=ToolIntentPlan(
            action=ToolIntentAction.USE_TOOLS,
            target_provider_types=["smartcmp"],
            target_tool_names=["smartcmp_list_pending"],
            reason="metadata_recall_matched",
        ),
    )

    assert plan.action is ToolIntentAction.USE_TOOLS
    assert plan.target_provider_types == ["smartcmp"]
    assert plan.target_tool_names == ["smartcmp_list_pending"]


def test_llm_first_intent_plan_does_not_let_metadata_override_artifact_request() -> None:
    plan = build_llm_first_intent_plan(
        user_message="将这些申请写入一个新的PPT",
        metadata_plan=ToolIntentPlan(
            action=ToolIntentAction.USE_TOOLS,
            target_provider_types=["smartcmp"],
            target_tool_names=["smartcmp_list_pending"],
            reason="metadata_recall_matched",
        ),
    )

    assert plan.action is ToolIntentAction.CREATE_ARTIFACT
    assert "Artifact-style follow-up" in plan.reason
