# -*- coding: utf-8 -*-
# Copyright 2021  Qianyun, Inc. All rights reserved.


from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2].parent
    / "atlasclaw-providers"
    / "providers"
    / "SmartCMP-Provider"
    / "skills"
    / "approval"
    / "scripts"
    / "list_pending.py"
)


def _load_module():
    scripts_dir = str(_SCRIPT_PATH.parent)
    inserted = False
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location("smartcmp_list_pending_script", _SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(scripts_dir)


def test_build_pending_query_params_defaults_to_all_pending() -> None:
    module = _load_module()

    params = module.build_pending_query_params(now_ms=1_700_000_000_000, days=None)

    assert params["page"] == 1
    assert params["size"] == 50
    assert params["stage"] == "pending"
    assert "startAtMin" not in params
    assert "startAtMax" not in params
    assert "rangeField" not in params


def test_build_pending_query_params_adds_time_window_when_days_specified() -> None:
    module = _load_module()

    now_ms = 1_700_000_000_000
    params = module.build_pending_query_params(now_ms=now_ms, days=7)

    assert params["stage"] == "pending"
    assert params["startAtMax"] == now_ms
    assert params["rangeField"] == "updatedDate"
    assert params["startAtMin"] < now_ms


def test_parse_days_from_argv_accepts_positive_integer_only() -> None:
    module = _load_module()

    assert module.parse_days_from_argv([]) is None
    assert module.parse_days_from_argv(["--days", "7"]) == 7
    assert module.parse_days_from_argv(["--days", "0"]) is None
    assert module.parse_days_from_argv(["--days", "-3"]) is None
    assert module.parse_days_from_argv(["--days", "abc"]) is None
