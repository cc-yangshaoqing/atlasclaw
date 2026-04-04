# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from app.atlasclaw.agent.tool_gate import CapabilityMatcher, ToolNecessityGate
from app.atlasclaw.agent.tool_gate_models import ToolGateDecision, ToolPolicyMode


class _ClassifierResult:
    def __init__(self, decision: ToolGateDecision | None) -> None:
        self._decision = decision

    async def classify(self, user_message: str, recent_history: list[dict]) -> ToolGateDecision | None:
        return self._decision


class _SyncClassifierResult:
    def __init__(self, decision: ToolGateDecision | None) -> None:
        self._decision = decision

    def classify(self, user_message: str, recent_history: list[dict]) -> ToolGateDecision | None:
        return self._decision


def test_gate_defaults_to_neutral_direct_answer_without_classifier() -> None:
    gate = ToolNecessityGate()
    decision = gate.classify("任何问题", [])
    assert decision.policy is ToolPolicyMode.ANSWER_DIRECT
    assert "No classifier decision" in decision.reason


def test_matcher_prefers_provider_for_private_provider_question() -> None:
    matcher = CapabilityMatcher(
        available_tools=[
            {"name": "web_search", "description": "Web search"},
            {"name": "jira_search", "description": "Search Jira issues", "capability_class": "provider:jira"},
        ]
    )
    result = matcher.match(["provider:jira"])
    assert result.tool_candidates[0].name == "jira_search"


def test_matcher_reports_partial_missing_capabilities() -> None:
    matcher = CapabilityMatcher(
        available_tools=[
            {"name": "web_search", "description": "Web search"},
        ]
    )

    result = matcher.match(["web_search", "browser"])

    assert [candidate.name for candidate in result.tool_candidates] == ["web_search"]
    assert result.missing_capabilities == ["browser"]
    assert result.resolved_policy is ToolPolicyMode.MUST_USE_TOOL


def test_matcher_infers_skill_capability_from_category() -> None:
    matcher = CapabilityMatcher(
        available_tools=[
            {
                "name": "custom_skill_runner",
                "description": "Run one workflow skill",
                "category": "skill",
            }
        ]
    )

    result = matcher.match(["skill"])

    assert result.missing_capabilities == []
    assert [candidate.name for candidate in result.tool_candidates] == ["custom_skill_runner"]
    assert result.tool_candidates[0].capability_class == "skill"


def test_matcher_resolves_openmeteo_weather_capability() -> None:
    matcher = CapabilityMatcher(
        available_tools=[
            {
                "name": "openmeteo_weather",
                "description": "Get forecast weather from Open-Meteo APIs",
            }
        ]
    )

    result = matcher.match(["weather"])

    assert result.missing_capabilities == []
    assert [candidate.name for candidate in result.tool_candidates] == ["openmeteo_weather"]
    assert result.tool_candidates[0].capability_class == "weather"


def test_matcher_prefers_name_mapping_over_coarse_explicit_capability_class() -> None:
    matcher = CapabilityMatcher(
        available_tools=[
            {
                "name": "web_search",
                "description": "Web search",
                "capability_class": "builtin:web",
            }
        ]
    )

    result = matcher.match(["web_search"])

    assert result.missing_capabilities == []
    assert [candidate.name for candidate in result.tool_candidates] == ["web_search"]
    assert result.tool_candidates[0].capability_class == "web_search"


@pytest.mark.asyncio
async def test_async_gate_prefers_classifier_result_over_default() -> None:
    gate = ToolNecessityGate()
    classifier = _ClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            needs_live_data=True,
            needs_grounded_verification=True,
            suggested_tool_classes=["web_search"],
            reason="Classifier judged that live data is required.",
            confidence=0.93,
            policy=ToolPolicyMode.MUST_USE_TOOL,
        )
    )

    decision = await gate.classify_async("任意问题", [], classifier=classifier)

    assert decision.policy is ToolPolicyMode.MUST_USE_TOOL
    assert decision.reason == "Classifier judged that live data is required."


@pytest.mark.asyncio
async def test_async_gate_falls_back_to_neutral_default_when_classifier_returns_none() -> None:
    gate = ToolNecessityGate()
    classifier = _ClassifierResult(None)

    decision = await gate.classify_async("任意问题", [], classifier=classifier)

    assert decision.policy is ToolPolicyMode.ANSWER_DIRECT
    assert "No classifier decision" in decision.reason


@pytest.mark.asyncio
async def test_async_gate_accepts_sync_classifier_result() -> None:
    gate = ToolNecessityGate()
    classifier = _SyncClassifierResult(
        ToolGateDecision(
            needs_tool=True,
            suggested_tool_classes=["browser"],
            reason="Synchronous classifier requires browser interaction.",
            confidence=0.81,
            policy=ToolPolicyMode.MUST_USE_TOOL,
        )
    )

    decision = await gate.classify_async("帮我发到知乎", [], classifier=classifier)

    assert decision.policy is ToolPolicyMode.MUST_USE_TOOL
    assert decision.suggested_tool_classes == ["browser"]
