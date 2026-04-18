# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.atlasclaw.skills.md_tool_runtime import ScriptInvocationConfig, create_script_wrapper


def test_script_wrapper_serializes_positional_and_flag_arguments(tmp_path: Path) -> None:
    script = tmp_path / "echo_args.py"
    script.write_text(
        "\n".join(
            [
                "import json, sys",
                "print(json.dumps({'argv': sys.argv[1:]}))",
            ]
        ),
        encoding="utf-8",
    )

    wrapper = create_script_wrapper(
        script,
        invocation_config=ScriptInvocationConfig(
            positional_args=("identifier",),
        ),
    )
    result = asyncio.run(wrapper(identifier="TIC20260316000001", days=90))

    assert result["success"] is True
    payload = json.loads(result["output"].strip())
    assert payload["argv"] == ["TIC20260316000001", "--days", "90"]


def test_script_wrapper_splits_repeatable_positional_arguments(tmp_path: Path) -> None:
    script = tmp_path / "echo_args.py"
    script.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "print(json.dumps({'argv': sys.argv[1:], 'env_ids': os.environ.get('IDS', '')}))",
            ]
        ),
        encoding="utf-8",
    )

    wrapper = create_script_wrapper(
        script,
        invocation_config=ScriptInvocationConfig(
            positional_args=("ids",),
            split_args=("ids",),
        ),
    )
    result = asyncio.run(wrapper(ids="id1 id2", reason="Approved"))

    assert result["success"] is True
    payload = json.loads(result["output"].strip())
    assert payload["argv"] == ["id1", "id2", "--reason", "Approved"]
    assert payload["env_ids"] == "id1 id2"


def test_script_wrapper_uses_flag_overrides_when_present(tmp_path: Path) -> None:
    script = tmp_path / "echo_args.py"
    script.write_text(
        "\n".join(
            [
                "import json, sys",
                "print(json.dumps({'argv': sys.argv[1:]}))",
            ]
        ),
        encoding="utf-8",
    )

    wrapper = create_script_wrapper(
        script,
        invocation_config=ScriptInvocationConfig(
            flag_name_overrides={"business_group_id": "--bg-id"},
        ),
    )
    result = asyncio.run(wrapper(business_group_id="bg-123"))

    assert result["success"] is True
    payload = json.loads(result["output"].strip())
    assert payload["argv"] == ["--bg-id", "bg-123"]


def test_script_wrapper_maps_json_body_to_json_flag_and_serializes_dict(tmp_path: Path) -> None:
    script = tmp_path / "echo_args.py"
    script.write_text(
        "\n".join(
            [
                "import json, sys",
                "argv = sys.argv[1:]",
                "parsed = json.loads(argv[1]) if len(argv) >= 2 and argv[0] == '--json' else None",
                "print(json.dumps({'argv': argv, 'parsed': parsed}, ensure_ascii=False))",
            ]
        ),
        encoding="utf-8",
    )

    wrapper = create_script_wrapper(script)
    result = asyncio.run(
        wrapper(
            json_body={
                "catalogId": "catalog-1",
                "businessGroupId": "bg-1",
                "name": "机房没网络了",
            }
        )
    )

    assert result["success"] is True
    payload = json.loads(result["output"].strip())
    assert payload["argv"][0] == "--json"
    assert payload["parsed"] == {
        "catalogId": "catalog-1",
        "businessGroupId": "bg-1",
        "name": "机房没网络了",
    }


def test_smartcmp_submit_wrapper_injects_user_login_id_from_context(tmp_path: Path) -> None:
    script = tmp_path / "submit.py"
    script.write_text(
        "\n".join(
            [
                "import json, sys",
                "argv = sys.argv[1:]",
                "parsed = json.loads(argv[1]) if len(argv) >= 2 and argv[0] == '--json' else None",
                "print(json.dumps({'argv': argv, 'parsed': parsed}, ensure_ascii=False))",
            ]
        ),
        encoding="utf-8",
    )

    class _UserInfo:
        user_id = "admin"

    class _Deps:
        user_info = _UserInfo()

    class _Ctx:
        deps = _Deps()

    wrapper = create_script_wrapper(script, provider_type="smartcmp")
    result = asyncio.run(
        wrapper(
            ctx=_Ctx(),
            json_body={
                "catalogName": "Linux VM",
                "businessGroupId": "bg-1",
                "name": "vm-01",
            },
        )
    )

    assert result["success"] is True
    payload = json.loads(result["output"].strip())
    assert payload["argv"][0] == "--json"
    assert payload["parsed"]["catalogName"] == "Linux VM"
    assert payload["parsed"]["userLoginId"] == "admin"


def test_smartcmp_list_components_wrapper_hides_info_banner(tmp_path: Path) -> None:
    script = tmp_path / "list_components.py"
    script.write_text("print('[INFO] Component metadata loaded.')", encoding="utf-8")

    wrapper = create_script_wrapper(script, provider_type="smartcmp")
    result = asyncio.run(wrapper())

    assert result["success"] is True
    assert result["output"] == ""


def test_smartcmp_list_os_templates_wrapper_strips_verbose_header(tmp_path: Path) -> None:
    script = tmp_path / "list_os_templates.py"
    script.write_text(
        "\n".join(
            [
                "print('')",
                "print('OS Templates  (osType=Linux, resourceBundleId=00101011-03d8-40f0-9ca9-21df162e013b)')",
                "print('=' * 60)",
                "print('  [1] CentOS')",
                "print('  [2] RedHat')",
                "print('')",
                "print('请选择OS模板（输入编号）：')",
            ]
        ),
        encoding="utf-8",
    )

    wrapper = create_script_wrapper(script, provider_type="smartcmp")
    result = asyncio.run(wrapper())

    assert result["success"] is True
    assert "resourceBundleId" not in result["output"]
    assert "[1] CentOS" in result["output"]
