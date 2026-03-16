"""Workspace initialization and management.

This module provides workspace directory structure initialization
and management for AtlasClaw.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class WorkspaceInitializer:
    """Initialize and manage workspace directory structure.
    
    The workspace directory (default: ./.atlasclaw) contains all AtlasClaw user data
    including agents, skills, channels, and user data. Providers are stored separately
    in a sibling directory configured via providers_root.
    """
    
    def __init__(self, workspace_path: str = "./.atlasclaw"):
        """Initialize workspace initializer.
        
        Args:
            workspace_path: Path to the workspace root directory (default: ./.atlasclaw).
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.users_dir = self.workspace_path / "users"
    
    def initialize(self) -> bool:
        """Initialize workspace directory structure.
        
        Creates the following structure:
        <workspace>/                 (default: ./.atlasclaw)
        ├── agents/
        ├── skills/
        ├── channels/
        └── users/
        
        Returns:
            True if initialization was successful.
        """
        try:
            # Create workspace directory structure
            self.workspace_path.mkdir(parents=True, exist_ok=True)
            (self.workspace_path / "agents").mkdir(exist_ok=True)
            (self.workspace_path / "skills").mkdir(exist_ok=True)
            (self.workspace_path / "channels").mkdir(exist_ok=True)
            
            # Create users directory inside workspace
            self.users_dir.mkdir(exist_ok=True)
            
            # Create default main agent if not exists
            self._create_default_main_agent()
            
            return True
        except Exception as e:
            print(f"[WorkspaceInitializer] Failed to initialize workspace: {e}")
            return False
    
    def _create_default_main_agent(self) -> None:
        """Create default main agent if it doesn't exist."""
        main_agent_dir = self.workspace_path / "agents" / "main"
        if main_agent_dir.exists():
            return
        
        main_agent_dir.mkdir(parents=True, exist_ok=True)
        
        # Create SOUL.md
        soul_md = main_agent_dir / "SOUL.md"
        if not soul_md.exists():
            soul_md.write_text(self._default_soul_md(), encoding="utf-8")
        
        # Create IDENTITY.md
        identity_md = main_agent_dir / "IDENTITY.md"
        if not identity_md.exists():
            identity_md.write_text(self._default_identity_md(), encoding="utf-8")
        
        # Create USER.md
        user_md = main_agent_dir / "USER.md"
        if not user_md.exists():
            user_md.write_text(self._default_user_md(), encoding="utf-8")
        
        # Create MEMORY.md
        memory_md = main_agent_dir / "MEMORY.md"
        if not memory_md.exists():
            memory_md.write_text(self._default_memory_md(), encoding="utf-8")
    
    def _default_soul_md(self) -> str:
        """Default SOUL.md content."""
        return '''---
agent_id: "main"
name: "企业助手"
version: "1.0"
---

## 系统提示词

你是企业的智能助手，帮助员工处理日常工作任务。

## 能力范围

- 回答企业相关问题
- 协助处理文档和数据
- 提供技术支持

## 可用 Providers

- jira
- confluence

## 可用 Skills

- query_knowledge
- create_ticket
'''
    
    def _default_identity_md(self) -> str:
        """Default IDENTITY.md content."""
        return '''---
agent_id: "main"
---

# IDENTITY.md - Agent 身份

## 基本信息

- **显示名称**: 小助手
- **头像**: 🤖
- **语气**: 专业、友好、简洁

## 交互风格

- 优先给出直接答案
- 需要时提供详细解释
- 使用中文回复
'''
    
    def _default_user_md(self) -> str:
        """Default USER.md content."""
        return '''---
agent_id: "main"
---

# USER.md - 用户交互方式

## 个性化设置

- 记住用户偏好
- 根据用户角色调整回答深度

## 主动行为

- 检测到重要信息时主动提醒
'''
    
    def _default_memory_md(self) -> str:
        """Default MEMORY.md content."""
        return '''---
agent_id: "main"
---

# MEMORY.md - 记忆策略

## 长期记忆

- 自动提取：是
- 提取触发：对话结束、关键决策点

## 上下文管理

- 最大轮数：20
- 压缩策略：摘要 + 关键决策保留
'''
    
    def is_initialized(self) -> bool:
        """Check if workspace is initialized."""
        return (
            self.workspace_path.exists()
            and (self.workspace_path / "agents").exists()
            and (self.workspace_path / "skills").exists()
            and self.users_dir.exists()
        )


class UserWorkspaceInitializer:
    """Initialize and manage user-specific workspace directories."""
    
    def __init__(self, workspace_path: str, user_id: str):
        """Initialize user workspace initializer.
        
        Args:
            workspace_path: Path to the workspace root directory.
            user_id: User identifier.
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.user_id = user_id
        self.user_dir = self.workspace_path / "users" / user_id
    
    def initialize(self) -> bool:
        """Initialize user directory structure.
        
        Creates the following structure:
        users/<user-id>/
        ├── atlasclaw.json
        ├── channels/
        ├── sessions/
        └── memory/
        
        Returns:
            True if initialization was successful.
        """
        try:
            # Create user directory structure
            self.user_dir.mkdir(parents=True, exist_ok=True)
            (self.user_dir / "channels").mkdir(exist_ok=True)
            (self.user_dir / "sessions").mkdir(exist_ok=True)
            (self.user_dir / "memory").mkdir(exist_ok=True)
            
            # Create default user config if not exists
            self._create_default_user_config()
            
            return True
        except Exception as e:
            print(f"[UserWorkspaceInitializer] Failed to initialize user workspace: {e}")
            return False
    
    def _create_default_user_config(self) -> None:
        """Create default user atlasclaw.json if it doesn't exist."""
        user_config_path = self.user_dir / "atlasclaw.json"
        if user_config_path.exists():
            return
        
        default_config = {
            "providers": {},
            "skills": {}
        }
        
        try:
            with open(user_config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[UserWorkspaceInitializer] Failed to create user config: {e}")
    
    def is_initialized(self) -> bool:
        """Check if user workspace is initialized."""
        return (
            self.user_dir.exists()
            and (self.user_dir / "channels").exists()
            and (self.user_dir / "sessions").exists()
            and (self.user_dir / "memory").exists()
        )
    
    def get_sessions_dir(self) -> Path:
        """Get user sessions directory."""
        return self.user_dir / "sessions"
    
    def get_memory_dir(self) -> Path:
        """Get user memory directory."""
        return self.user_dir / "memory"
