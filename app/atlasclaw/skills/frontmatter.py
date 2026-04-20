# -*- coding: utf-8 -*-
# Copyright 2021  Qianyun, Inc. All rights reserved.

"""YAML frontmatter parsing for markdown skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - fallback only used in misconfigured environments
    yaml = None


@dataclass
class FrontmatterResult:
    """Frontmatter parse result."""

    metadata: dict[str, Any] = field(default_factory=dict)
    body: str = ""


def parse_frontmatter(content: str) -> FrontmatterResult:
    """Parse Markdown YAML frontmatter.

    Returns empty metadata and the original content when:
    - the file has no leading frontmatter fence
    - the closing fence is missing
    - the frontmatter cannot be parsed as a YAML mapping
    """
    content = content.lstrip("\ufeff")
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")

    if not lines or lines[0].strip() != "---":
        return FrontmatterResult(metadata={}, body=content)

    close_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx == -1:
        return FrontmatterResult(metadata={}, body=content)

    metadata = _parse_frontmatter_mapping("\n".join(lines[1:close_idx]))
    body_lines = lines[close_idx + 1 :]
    body = "\n".join(body_lines)
    return FrontmatterResult(metadata=metadata, body=body)


def _parse_frontmatter_mapping(frontmatter: str) -> dict[str, Any]:
    """Parse the YAML mapping portion of a frontmatter block."""
    if yaml is not None:
        try:
            loaded = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return _parse_frontmatter_mapping_legacy(frontmatter)


def _parse_frontmatter_mapping_legacy(frontmatter: str) -> dict[str, Any]:
    """Fallback parser for environments without PyYAML.

    This keeps basic scalar and list support so the runtime remains usable
    even if the YAML dependency is unexpectedly unavailable.
    """
    metadata: dict[str, Any] = {}
    current_key = ""
    current_list: list[str] = []

    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_key:
                item_value = stripped[2:].strip()
                if len(item_value) >= 2 and (
                    (item_value[0] == "'" and item_value[-1] == "'")
                    or (item_value[0] == '"' and item_value[-1] == '"')
                ):
                    item_value = item_value[1:-1]
                current_list.append(item_value)
            continue
        if current_key and current_list:
            metadata[current_key] = current_list
            current_key = ""
            current_list = []
        colon_pos = stripped.find(":")
        if colon_pos == -1:
            continue
        key = stripped[:colon_pos].strip()
        value = stripped[colon_pos + 1 :].strip()
        if not value:
            current_key = key
            current_list = []
            continue
        if len(value) >= 2 and (
            (value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')
        ):
            value = value[1:-1]
        if key:
            metadata[key] = value

    if current_key and current_list:
        metadata[current_key] = current_list
    return metadata
