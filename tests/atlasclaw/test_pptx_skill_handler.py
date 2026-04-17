# -*- coding: utf-8 -*-
# Copyright 2021  Qianyun, Inc. All rights reserved.


from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from app.atlasclaw.session.context import SessionKey, SessionMetadata


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2].parent
    / "atlasclaw-providers"
    / "skills"
    / "pptx"
    / "scripts"
    / "handler.py"
)


def _load_module():
    scripts_dir = str(_SCRIPT_PATH.parent)
    inserted = False
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location("pptx_skill_handler_script", _SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(scripts_dir)


class _FakeSessionManager:
    def __init__(self, *, workspace_path: Path, user_id: str, session_key: str, session_id: str) -> None:
        self.workspace_path = workspace_path
        self.user_id = user_id
        self.sessions_dir = workspace_path / "users" / user_id / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_cache = {
            session_key: SessionMetadata(session_key=session_key, session_id=session_id)
        }

    def _get_transcript_path(self, session: SessionMetadata) -> Path:
        parsed = SessionKey.from_string(session.session_key)
        if parsed.thread_id:
            filename = f"{session.session_id}-topic-{parsed.thread_id}.jsonl"
        else:
            filename = f"{session.session_id}.jsonl"
        return self.sessions_dir / filename


def _build_ctx(*, workspace_path: Path, session_key: str = ""):
    session_manager = _FakeSessionManager(
        workspace_path=workspace_path,
        user_id="admin",
        session_key=session_key or "agent:main:user:admin:web:dm:admin:topic:test-thread",
        session_id="session-test",
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            session_manager=session_manager,
            session_key=session_key or "agent:main:user:admin:web:dm:admin:topic:test-thread",
            user_info=SimpleNamespace(user_id="admin"),
        )
    )
    return ctx, session_manager


def test_create_deck_handler_accepts_string_items(tmp_path: Path) -> None:
    module = _load_module()
    ctx, _ = _build_ctx(workspace_path=tmp_path / "workspace")

    result = module.create_deck_handler(
        ctx,
        items=["工单概览", "当前共有 3 项待审批申请", "请尽快安排审批"],
        title="CMP 待审批申请汇总",
        output_filename="string-items.pptx",
    )

    assert result["success"] is True
    assert result["item_count"] == 3
    assert Path(result["file_path"]).is_file()
    assert Path(result["file_path"]).name == "string-items.pptx"


def test_create_deck_handler_recovers_pending_items_from_transcript(tmp_path: Path) -> None:
    module = _load_module()
    ctx, session_manager = _build_ctx(workspace_path=tmp_path / "workspace")
    session = session_manager._metadata_cache[ctx.deps.session_key]
    transcript_path = session_manager._get_transcript_path(session)

    approval_meta = [
        {
            "index": 1,
            "id": "APR-1",
            "workflowId": "TIC20260316000001",
            "name": "Test ticket for build verification",
            "approvalStep": "一级审批",
            "currentApprover": "待分配",
            "approvalId": "APR-20260316-0001",
        },
        {
            "index": 2,
            "id": "APR-2",
            "workflowId": "TIC20260313000006",
            "name": "加急加急",
            "approvalStep": "一级审批",
            "currentApprover": "待分配",
            "approvalId": "APR-20260313-0006",
        },
        {
            "index": 3,
            "id": "APR-3",
            "workflowId": "TIC20260313000004",
            "name": "",
            "approvalStep": "一级审批",
            "currentApprover": "待分配",
            "approvalId": "APR-20260313-0004",
        },
    ]
    tool_output = (
        "待审批列表 - 共 3 项\n"
        "##APPROVAL_META_START##\n"
        f"{json.dumps(approval_meta, ensure_ascii=False)}\n"
        "##APPROVAL_META_END##\n"
    )
    transcript_path.write_text(
        json.dumps(
            {
                "role": "tool",
                "content": {"success": True, "output": tool_output},
                "tool_name": "smartcmp_list_pending",
                "tool_call_id": "call-1",
                "tool_calls": [],
                "tool_results": [],
                "metadata": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.create_deck_handler(
        ctx,
        items=[],
        title="CMP 待审批申请汇总",
        output_filename="recovered-items.pptx",
    )

    assert result["success"] is True
    assert result["item_count"] == 3
    assert result["slide_count"] == 5
    assert Path(result["file_path"]).is_file()
