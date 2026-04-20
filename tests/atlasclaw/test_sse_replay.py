# Copyright 2021  Qianyun, Inc. All rights reserved.


import asyncio

import pytest

from app.atlasclaw.api.sse import SSEManager


@pytest.mark.asyncio
async def test_late_subscriber_replays_buffered_events_without_last_event_id():
    manager = SSEManager(heartbeat_interval=0.01, stream_timeout=1.0)
    run_id = "run-replay"

    manager.create_stream(run_id)
    manager.push_lifecycle(run_id, "start")
    manager.push_assistant(run_id, "hello")

    generator = manager._event_generator(run_id)

    first_event = await asyncio.wait_for(generator.__anext__(), timeout=0.1)
    second_event = await asyncio.wait_for(generator.__anext__(), timeout=0.1)

    manager.close_stream(run_id)
    third_event = await asyncio.wait_for(generator.__anext__(), timeout=0.1)

    assert first_event["event"] == "lifecycle"
    assert '"phase": "start"' in first_event["data"]
    assert second_event["event"] == "assistant"
    assert '"text": "hello"' in second_event["data"]
    assert third_event["event"] == "lifecycle"
    assert '"phase": "end"' in third_event["data"]


@pytest.mark.asyncio
async def test_closed_stream_replay_emits_lifecycle_end_for_late_subscriber():
    manager = SSEManager(heartbeat_interval=0.01, stream_timeout=1.0)
    run_id = "run-closed-replay"

    manager.create_stream(run_id)
    manager.push_lifecycle(run_id, "start")
    manager.push_assistant(run_id, "hello")
    manager.close_stream(run_id)

    generator = manager._event_generator(run_id)

    first_event = await asyncio.wait_for(generator.__anext__(), timeout=0.1)
    second_event = await asyncio.wait_for(generator.__anext__(), timeout=0.1)
    third_event = await asyncio.wait_for(generator.__anext__(), timeout=0.1)

    assert first_event["event"] == "lifecycle"
    assert '"phase": "start"' in first_event["data"]
    assert second_event["event"] == "assistant"
    assert '"text": "hello"' in second_event["data"]
    assert third_event["event"] == "lifecycle"
    assert '"phase": "end"' in third_event["data"]


def test_push_assistant_strips_tool_meta_block_contents():
    manager = SSEManager()
    run_id = "run-tool-meta"

    manager.create_stream(run_id)
    manager.push_assistant(
        run_id,
        "Visible before <tool_meta>secret internal metadata</tool_meta> visible after",
    )

    stream = manager.get_stream(run_id)

    assert stream is not None
    assert stream.events[-1].data["text"] == "Visible before  visible after"
