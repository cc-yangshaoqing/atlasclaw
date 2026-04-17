# Copyright 2021  Qianyun, Inc. All rights reserved.


"""Agent execution layer for AtlasClaw.

The `agent` package groups together the components responsible for prompt
construction, iterative agent execution, response compaction, and stream
chunking.
"""

from app.atlasclaw.agent.stream import StreamEvent, BlockChunker
from app.atlasclaw.agent.compaction import CompactionPipeline, CompactionConfig

__all__ = [
    "StreamEvent",
    "BlockChunker",
    "CompactionPipeline",
    "CompactionConfig",
]
