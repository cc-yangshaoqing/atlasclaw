# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Optional

from app.atlasclaw.agent.tool_gate_models import ToolIntentAction, ToolIntentPlan


_ARTIFACT_KEYWORDS = (
    "ppt",
    "pptx",
    "powerpoint",
    "slide deck",
    "slides",
    "markdown",
    "md",
    "文档",
    "文件",
    "导出",
    "保存",
    "写入",
    "生成",
    "汇报",
    "演示文稿",
    "幻灯片",
    "报告",
)

_GENERIC_FALLBACK_CAPABILITY_CLASSES = {
    "web_search",
    "web_fetch",
    "browser",
}

_GENERIC_FALLBACK_TOOL_NAMES = {
    "web_search",
    "web_fetch",
    "browser",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def resolve_artifact_goal(user_message: str) -> Optional[dict[str, Any]]:
    normalized = _normalize_text(user_message).lower()
    if not normalized:
        return None

    if any(keyword in normalized for keyword in ("pptx", "ppt", "powerpoint", "演示文稿", "幻灯片")):
        return {
            "kind": "pptx",
            "label": "PowerPoint deck",
            "extensions": [".pptx", ".ppt"],
        }
    if any(keyword in normalized for keyword in ("markdown", " md", ".md", "markdown文件")):
        return {
            "kind": "markdown",
            "label": "Markdown file",
            "extensions": [".md", ".markdown"],
        }
    if any(keyword in normalized for keyword in ("报告", "report")):
        return {
            "kind": "report",
            "label": "Report artifact",
            "extensions": [".md", ".markdown", ".pptx", ".ppt", ".docx", ".pdf", ".txt"],
        }
    if any(keyword in normalized for keyword in ("文档", "文件", "导出", "保存", "写入", "生成")):
        return {
            "kind": "file",
            "label": "File artifact",
            "extensions": [],
        }
    return None


def looks_like_artifact_request(user_message: str) -> bool:
    normalized = _normalize_text(user_message).lower()
    if not normalized:
        return False
    return resolve_artifact_goal(user_message) is not None or any(
        keyword in normalized for keyword in _ARTIFACT_KEYWORDS
    )


def _collect_artifact_path_candidates(payload: Any) -> list[str]:
    candidates: list[str] = []
    if payload is None:
        return candidates
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = _normalize_text(key).lower()
            if normalized_key in {
                "file_path",
                "path",
                "output_path",
                "artifact_path",
                "report_path",
                "ppt_path",
                "markdown_path",
            }:
                normalized_value = _normalize_text(value)
                if normalized_value:
                    candidates.append(normalized_value)
            candidates.extend(_collect_artifact_path_candidates(value))
        return candidates
    if isinstance(payload, list):
        for item in payload:
            candidates.extend(_collect_artifact_path_candidates(item))
        return candidates
    text = _normalize_text(payload)
    if not text:
        return candidates
    if "file written:" in text.lower():
        candidates.append(text.split(":", 1)[-1].strip())
    return candidates


def tool_output_satisfies_artifact_goal(
    *,
    tool_name: str,
    payload: Any,
    artifact_goal: Optional[dict[str, Any]],
) -> bool:
    if not artifact_goal:
        return True

    goal_kind = _normalize_text(artifact_goal.get("kind", "")).lower()
    extensions = [
        _normalize_text(item).lower()
        for item in list(artifact_goal.get("extensions", []) or [])
        if _normalize_text(item)
    ]
    path_candidates = [item.lower() for item in _collect_artifact_path_candidates(payload)]
    normalized_tool_name = _normalize_text(tool_name).lower()

    if extensions:
        for candidate in path_candidates:
            if any(candidate.endswith(extension) for extension in extensions):
                return True

    if goal_kind == "file" and path_candidates:
        return True
    if goal_kind == "report" and path_candidates:
        return True
    if goal_kind == "pptx" and "ppt" in normalized_tool_name and path_candidates:
        return True
    if goal_kind == "markdown" and "write" in normalized_tool_name and path_candidates:
        return True
    return False


def messages_satisfy_artifact_goal(
    *,
    messages: list[dict[str, Any]],
    start_index: int,
    target_tool_names: list[str],
    artifact_goal: Optional[dict[str, Any]],
) -> bool:
    if not artifact_goal:
        return True

    target_names = {str(name).strip() for name in target_tool_names if str(name).strip()}
    if not target_names:
        return False

    safe_start = max(0, min(int(start_index), len(messages)))
    for message in messages[safe_start:]:
        if not isinstance(message, dict):
            continue
        role = _normalize_text(message.get("role", "")).lower()
        if role in {"tool", "toolresult", "tool_result"}:
            tool_name = _normalize_text(message.get("tool_name", "") or message.get("name", ""))
            if tool_name in target_names and tool_output_satisfies_artifact_goal(
                tool_name=tool_name,
                payload=message.get("content"),
                artifact_goal=artifact_goal,
            ):
                return True
        tool_results = message.get("tool_results")
        if not isinstance(tool_results, list):
            continue
        for result in tool_results:
            if not isinstance(result, dict):
                continue
            tool_name = _normalize_text(result.get("tool_name", "") or result.get("name", ""))
            if tool_name not in target_names:
                continue
            if tool_output_satisfies_artifact_goal(
                tool_name=tool_name,
                payload=result.get("content", result),
                artifact_goal=artifact_goal,
            ):
                return True
    return False


def selected_capability_ids_from_intent_plan(intent_plan: Optional[ToolIntentPlan]) -> list[str]:
    """Build stable capability identifiers from the current intent plan."""
    if intent_plan is None:
        return []

    selected_ids: list[str] = []
    seen: set[str] = set()

    def _append(prefix: str, values: list[str]) -> None:
        for value in values:
            normalized = _normalize_text(value)
            if not normalized:
                continue
            capability_id = f"{prefix}:{normalized}"
            if capability_id in seen:
                continue
            seen.add(capability_id)
            selected_ids.append(capability_id)

    _append("tool", list(intent_plan.target_tool_names or []))
    _append("skill", list(intent_plan.target_skill_names or []))
    _append("provider", list(intent_plan.target_provider_types or []))
    _append("capability", list(intent_plan.target_capability_classes or []))
    _append("group", list(intent_plan.target_group_ids or []))
    return selected_ids


def should_force_metadata_tool_path(
    *,
    user_message: str,
    metadata_plan: Optional[ToolIntentPlan],
) -> bool:
    if metadata_plan is None or metadata_plan.action is not ToolIntentAction.USE_TOOLS:
        return False
    if looks_like_artifact_request(user_message):
        return False

    target_provider_types = {
        _normalize_text(item).lower()
        for item in list(metadata_plan.target_provider_types or [])
        if _normalize_text(item)
    }
    target_skill_names = {
        _normalize_text(item).lower()
        for item in list(metadata_plan.target_skill_names or [])
        if _normalize_text(item)
    }
    target_capability_classes = {
        _normalize_text(item).lower()
        for item in list(metadata_plan.target_capability_classes or [])
        if _normalize_text(item)
    }
    target_tool_names = {
        _normalize_text(item)
        for item in list(metadata_plan.target_tool_names or [])
        if _normalize_text(item)
    }

    if target_provider_types or target_skill_names:
        return True

    if target_capability_classes.difference(_GENERIC_FALLBACK_CAPABILITY_CLASSES):
        return True

    if target_tool_names.difference(_GENERIC_FALLBACK_TOOL_NAMES):
        return True

    return False


def build_llm_first_intent_plan(
    *,
    user_message: str,
    metadata_plan: Optional[ToolIntentPlan],
) -> ToolIntentPlan:
    if should_force_metadata_tool_path(
        user_message=user_message,
        metadata_plan=metadata_plan,
    ):
        return metadata_plan.model_copy(
            update={
                "reason": (
                    _normalize_text(metadata_plan.reason)
                    or "Strong provider/skill metadata match requires real tool execution."
                )
            }
        )

    artifact_goal = resolve_artifact_goal(user_message)
    if artifact_goal is not None:
        return ToolIntentPlan(
            action=ToolIntentAction.CREATE_ARTIFACT,
            reason=(
                "Artifact-style follow-up detected. Keep full context and let the main model "
                "decide whether to create an artifact, ask for clarification, or use tools."
            ),
        )

    return ToolIntentPlan(
        action=ToolIntentAction.DIRECT_ANSWER,
        reason=(
            "LLM-first runtime routing is active. Metadata may bias visible capabilities, "
            "but the main model decides whether this turn needs tools."
        ),
    )
