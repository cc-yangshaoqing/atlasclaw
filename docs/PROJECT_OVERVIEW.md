# AtlasClaw-Core Project Overview

> **DEPRECATED**: This document has been superseded by [Architecture](./ARCHITECTURE.MD).
> Please refer to the canonical architecture document for up-to-date information.

## Introduction

**AtlasClaw** is an enterprise-grade AI Agent framework designed to enable employees to interact with multiple enterprise systems through a unified conversational AI interface. It addresses the fragmentation challenges faced by enterprise software teams working across CRM, ITSM, monitoring, HR, finance, and other systems.

---

## Core Design Philosophy

### Thin Core, Rich Providers

The architecture follows a "Thin Core, Rich Providers" pattern:
- **Core**: Reusable Agent logic, API layer, session management
- **Providers**: Platform-specific integrations (Jira, ServiceNow, etc.)

### Permission Inheritance

Every action runs under the authenticated user's real access permissions:
- No RBAC bypass
- No privilege escalation
- Audit trails remain in source systems

### Multi-Channel Access

Supports multiple entry points:
- Web UI (DeepChat-based)
- Embedded panels
- Chat platforms (Slack, Teams)
- Programmatic webhooks

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           API Layer                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   REST API  │  │  WebSocket  │  │    SSE      │  │  Gateway        │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│                         Agent Engine                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │    Runner   │  │   Routing   │  │PromptBuilder│  │  Stream/Chunker │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│                      Core Infrastructure                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   Config    │  │    Deps     │  │   Tenant    │  │Execution Context│ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│                     Data & State Management                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   Session   │  │    Memory   │  │    Queue    │  │     Hooks       │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│                     Skills & Tools System                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │SkillRegistry│  │   Tools     │  │  Built-in   │  │   Providers     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│                      Authentication                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │  Middleware │  │  Strategy   │  │  Providers  │  │  Shadow Store   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
AtlasClaw-Core/
├── app/
│   ├── frontend/              # Web UI (DeepChat + custom)
│   └── atlasclaw/               # Core backend
│       ├── agent/             # Agent engine
│       ├── api/               # API layer
│       ├── auth/              # Authentication system
│       ├── channels/          # Channel adapters
│       ├── core/              # Core infrastructure
│       ├── hooks/             # Hook system
│       ├── memory/            # Memory management
│       ├── providers/         # Built-in providers
│       ├── session/           # Session management
│       ├── skills/            # Skills system
│       ├── tools/             # Built-in tools
│       └── workflow/          # Workflow engine
├── tests/                     # Test suite
├── docs/                      # Documentation
└── openspec/                  # OpenSpec specifications
```

---

## Key Components

### 1. Agent Runner (`app/atlasclaw/agent/runner.py`)

The AgentRunner is a PydanticAI-based streaming Agent executor providing:

- **Checkpoint Control**: Abort signal checks, timeout checks, context checks
- **Tool Call Safety Limits**: Maximum tool call limits (default: 50)
- **Message Queue Injection**: Steering messages from session queue
- **Lifecycle Hooks**: `before_agent_start`, `llm_input`, `llm_output`, `before_tool_call`, `after_tool_call`, `agent_end`

```python
class AgentRunner:
    async def run(
        self,
        session_key: str,
        user_message: str,
        deps: SkillDeps,
        max_tool_calls: int = 50,
        timeout_seconds: int = 600,
    ) -> AsyncIterator[StreamEvent]:
        # Execute Agent and yield streaming events
```

### 2. Prompt Builder (`app/atlasclaw/agent/prompt_builder.py`)

Supports three modes of system prompt building:

| Mode | Description |
|------|-------------|
| `FULL` | Complete runtime prompt (identity, tools, security, skills, workspace, docs) |
| `MINIMAL` | Sub-agent mode without optional runtime parts |
| `NONE` | Basic identity line only |

### 3. Skill Registry (`app/atlasclaw/skills/registry.py`)

Manages executable Python Skills and Markdown-based Skill metadata:

- **Executable Skills**: Skills with Python handler functions
- **MD Skills**: Metadata Skills loaded from `SKILL.md` files
- **Search Path Priority**: Workspace > User > Built-in

### 4. Session Manager (`app/atlasclaw/session/manager.py`)

Handles session persistence and management:

- Session creation, retrieval, and deletion
- Message history management
- Session reset and compaction

### 5. Memory System (`app/atlasclaw/memory/manager.py`)

Provides long-term memory capabilities:

- Vector-based semantic search
- Full-text search
- Hybrid scoring (vector + full-text)

---

## Design Patterns

### Dependency Injection

Request-scoped dependency injection via `SkillDeps`:

```python
@dataclass
class SkillDeps:
    user_info: UserInfo
    session_key: str
    channel: str
    abort_signal: asyncio.Event
    session_manager: Optional[Any] = None
    memory_manager: Optional[Any] = None
    extra: dict[str, Any] = field(default_factory=dict)
```

### Strategy Pattern

Authentication system supports multiple providers:

- `NoneProvider`: Anonymous mode
- `ApiKeyProvider`: API Key authentication
- `OIDCProvider`: OIDC authentication
- `SmartCMPProvider`: SmartCMP integration

### Adapter Pattern

Channel adapters unify different communication protocols:

```python
class ChannelAdapter(ABC):
    @abstractmethod
    async def send(self, message: OutboundMessage) -> SendResult: ...
    
    @abstractmethod
    async def receive(self) -> AsyncIterator[InboundMessage]: ...
```

### Registry Pattern

- `SkillRegistry`: Skills registration and management
- `ServiceProviderRegistry`: Service provider registration
- `ToolCatalog`: Tool catalog and configuration

### Workflow Pattern

Step-based workflow engine supporting dependencies and conditional branches:

```python
engine = WorkflowEngine[MyState]()

@engine.step()
async def step1(state: MyState) -> MyState:
    state.count += 1
    return state

@engine.step(after=["step1"])
async def step2(state: MyState) -> MyState:
    state.message = f"Count is {state.count}"
    return state
```

### Hook Pattern

Supports sequential and parallel hook execution:

```python
class HookPhase(str, Enum):
    BEFORE_AGENT_START = "before_agent_start"
    AGENT_END = "agent_end"
    LLM_INPUT = "llm_input"
    LLM_OUTPUT = "llm_output"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
```

---

## Technology Stack

### Backend

| Category | Technology | Version | Purpose |
|----------|------------|---------|---------|
| Web Framework | FastAPI | >=0.109.0 | REST API and WebSocket |
| ASGI Server | Uvicorn | >=0.27.0 | Async server |
| Data Validation | Pydantic | >=2.6.0 | Data models and validation |
| AI Framework | PydanticAI | >=0.0.14 | Agent runtime |
| LLM Client | OpenAI | >=1.12.0 | LLM API calls |
| HTTP Client | HTTPX | >=0.26.0 | Async HTTP |
| File Operations | aiofiles | >=23.2.0 | Async file I/O |
| SSE | sse-starlette | >=2.0.0 | Server-sent events |
| Testing | pytest | >=8.0.0 | Test framework |

### Frontend

| Category | Technology | Purpose |
|----------|------------|---------|
| UI Components | DeepChat | Chat interface |
| Build Tool | Rollup | Module bundling |
| Testing | Jest | JavaScript testing |
| i18n | Custom | Multi-language support |

---

## Extension Points

### Provider Extension

Providers are the primary extension point:

```
providers/<provider-name>/
├── PROVIDER.md           # Provider documentation
├── README.md             # Description
└── skills/
    └── <skill-name>/
        ├── SKILL.md      # Skill definition
        └── scripts/      # Execution scripts
```

### Skills Extension

Two types of Skills supported:

**1. Markdown Skills (Declarative)**
```markdown
---
name: my-skill
description: My custom Skill
category: utility
entrypoint: handler.py:handler
---

# Skill Documentation
...
```

**2. Python Skills (Programmatic)**
```python
from pydantic_ai import RunContext
from app.atlasclaw.core.deps import SkillDeps

async def my_skill(ctx: RunContext[SkillDeps], param: str) -> dict:
    return {"result": f"Processed: {param}"}
```

### Tool Extension

Define tool combinations via `ToolProfile`:

```python
class ToolProfile(str, Enum):
    MINIMAL = "minimal"       # Minimal toolset
    CODING = "coding"         # Coding toolset
    MESSAGING = "messaging"   # Messaging toolset
    FULL = "full"             # Full toolset
```

### Auth Provider Extension

Implement `AuthProvider` interface:

```python
class MyAuthProvider(AuthProvider):
    async def authenticate(self, credential: str) -> AuthResult:
        # Implement authentication logic
        pass
    
    def provider_name(self) -> str:
        return "my_provider"
```

---

## Configuration Management

### Configuration Hierarchy

Configuration loaded in priority order (high to low):

1. **Runtime overrides** (via `config_manager.set()`)
2. **Environment variables** (`ATLASCLAW_*` prefix)
3. **Config file** (`atlasclaw.json` / `atlasclaw.yaml`)
4. **Defaults** (`config_schema.py`)

### Configuration Format

```json
{
  "model": {
    "primary": "kimi/kimi-k2.5",
    "fallbacks": [],
    "temperature": 0.7,
    "providers": {
      "kimi": {
        "base_url": "${ANTHROPIC_BASE_URL}",
        "api_key": "${ANTHROPIC_API_KEY}",
        "api_type": "anthropic"
      }
    }
  },
  
  "service_providers": {
    "jira": {
      "prod": {
        "base_url": "https://jira.corp.com",
        "token": "${JIRA_PROD_TOKEN}"
      }
    }
  },
  
  "agent_defaults": {
    "timeout_seconds": 600,
    "max_concurrent": 4,
    "max_tool_calls": 50
  }
}
```

### Environment Variables

Format: `ATLASCLAW_<PATH>__<KEY>`

```bash
ATLASCLAW_AGENT_DEFAULTS__TIMEOUT_SECONDS=300
ATLASCLAW_MODEL__TEMPERATURE=0.5
```

Configuration files support `${VAR_NAME}` syntax for environment variable references.

---

## Testing Strategy

### Test Organization

```
tests/
├── conftest.py                    # pytest configuration
├── atlasclaw.test.json              # Test configuration
├── atlasclaw/                       # Python tests
│   ├── test_core.py
│   ├── test_agent.py
│   ├── test_agent_integration.py
│   ├── test_e2e_api.py
│   ├── auth/
│   ├── memory/
│   ├── session/
│   └── providers/
└── frontend/                      # Frontend tests
```

### Test Markers

| Marker | Description | Command |
|--------|-------------|---------|
| `slow` | Slow tests (> 1s) | `pytest -m "not slow"` |
| `integration` | Integration tests | `pytest -m integration` |
| `e2e` | End-to-end tests | `pytest -m e2e` |
| `llm` | Tests requiring LLM API | `pytest -m llm` |

### Running Tests

```bash
# Run all tests
pytest tests/atlasclaw -q

# Run LLM integration tests
pytest tests/atlasclaw/test_agent_integration.py -v -m llm

# Run E2E tests
pytest tests/atlasclaw/test_e2e_api.py -v -m e2e

# Run with coverage
pytest --cov=app.atlasclaw --cov-report=term-missing
```

---

## Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Agent Framework** | PydanticAI | Type-safe, structured output, tool calling |
| **Web Framework** | FastAPI | Async-native, auto API docs, type hints |
| **Configuration** | Pydantic + layered loading | Type-safe, flexible overrides |
| **Authentication** | Strategy pattern + shadow users | Multiple auth sources, unified user model |
| **Storage** | File system (JSON/JSONL/Markdown) | Simple, version-controllable, debuggable |
| **Multi-tenancy** | Path isolation | Simple, effective, easy backup/migration |
| **Streaming** | SSE | Simpler than WebSocket, supports auto-reconnect |
| **Skills System** | Markdown + Python hybrid | Flexible combination of docs and logic |

---

## Documentation References

- [README.md](../README.md) - Project overview and quick start
- [AGENTS.md](../AGENTS.md) - Developer coding guide
- [QODER.md](../QODER.md) - OpenSpec guide
- [openspec/AGENTS.md](../openspec/AGENTS.md) - Specification-driven development
- [docs/images/architecture/](../docs/images/architecture/) - Architecture diagrams
