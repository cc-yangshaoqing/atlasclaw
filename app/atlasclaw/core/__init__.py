# Copyright 2021  Qianyun, Inc. All rights reserved.


"""



Includes:
- deps:SkillDeps dependency-injection container(PydanticAI RunContext[T] typeparameter)
- config:Configuration manager
- config_schema:configuration Schema(Pydantic model)
"""

from app.atlasclaw.core.deps import SkillDeps

__all__ = ["SkillDeps"]
