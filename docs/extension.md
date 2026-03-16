# AtlasClaw Extensions Architecture Design

Based on current AtlasClaw implementation and Channel Integrations design, this document provides extensible Auth and Channel mechanisms.

## Design Principles

1. **Built-in + Scannable**: Core Auth and Channel types are built-in, while automatically scanning extensions under the providers directory
2. **Separation of Concerns**: Auth, Channel, and Skills are independent, with no forced unified interface
3. **User Isolation**: Channel connections are stored per user, Auth is per configuration instance
4. **Protocol First**: Use Python Protocol and ABC to define contracts, rather than forcing inheritance
5. **Long Connection First**: All Channels prioritize long connection (WebSocket/Socket Mode), Webhook as fallback

## Overall Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AtlasClaw Extension Architecture                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │   AuthProvider  │  │  ChannelHandler │  │        Skills               │  │
│  │   (Auth Provider)   │  │  (Channel Handler)   │  │      (Skill Registry)            │  │
│  │                 │  │                 │  │                             │  │
│  │ • OIDC          │  │ • Feishu        │  │ • Executable                │  │
│  │ • OAuth2        │  │ • Slack         │  │ • Markdown                  │  │
│  │ • API Key       │  │ • WhatsApp      │  │ • Hybrid                    │  │
│  │ • SAML          │  │ • WebSocket     │  │                             │  │
│  │ • (Provider Scan) │  │ • SSE           │  │                             │  │
│  │                 │  │ • REST          │  │                             │  │
│  │                 │  │ • (Provider Scan) │  │                             │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │
│           │                    │                        │                   │
│           ▼                    ▼                        ▼                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Registry (Registration Tables)                             │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │   │
│  │  │AuthRegistry  │  │ChannelRegistry│  │    SkillRegistry         │  │   │
│  │  │              │  │              │  │                          │  │   │
│  │  │register()    │  │register()    │  │   register()             │  │   │
│  │  │get()         │  │get()         │  │   execute()              │  │   │
│  │  │list()        │  │list()        │  │   load_from_directory()  │  │   │
│  │  │scan_providers│  │scan_providers│  │                          │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 1. Unified Provider Directory Scanning Mechanism

Auth, Channel, and Skills all use the same directory scanning approach to load extensions from providers.

### 1.1 Directory Structure

```
providers/                         # Configured via providers_root (default: ../providers)
└── <provider_name>/
    ├── PROVIDER.md
    ├── auth/                    # Auth extensions (optional)
    │   └── <auth_type>.py       # AuthProvider implementation
    ├── channels/                # Channel extensions (optional)
    │   └── <channel_type>.py    # ChannelHandler implementation
    └── skills/                  # Skills extensions (optional)
        └── <skill_name>/
            ├── SKILL.md
            └── scripts/
```

### 1.2 Scanning and Loading Process

```python
# Unified scanning mechanism
class ProviderScanner:
    """Scan auth, channel, and skills extensions under providers directory"""
    
    @staticmethod
    def scan_providers(providers_dir: Path):
        """Scan all provider directories"""
        for provider_path in providers_dir.iterdir():
            if not provider_path.is_dir():
                continue
            
            provider_name = provider_path.name
            
            # 1. Scan Auth extensions
            auth_dir = provider_path / "auth"
            if auth_dir.exists():
                ProviderScanner._scan_auth_extensions(auth_dir, provider_name)
            
            # 2. Scan Channel extensions
            channels_dir = provider_path / "channels"
            if channels_dir.exists():
                ProviderScanner._scan_channel_extensions(channels_dir, provider_name)
            
            # 3. Scan Skills extensions (already exists)
            skills_dir = provider_path / "skills"
            if skills_dir.exists():
                SkillRegistry.load_from_directory(skills_dir, location="built-in")
    
    @staticmethod
    def _scan_auth_extensions(auth_dir: Path, provider_name: str):
        """Scan Auth extensions"""
        for auth_file in auth_dir.glob("*.py"):
            if auth_file.name.startswith("_"):
                continue
            # Dynamically import and register
            module = import_module_from_path(auth_file)
            if hasattr(module, "AuthProvider"):
                auth_class = module.AuthProvider
                auth_id = getattr(auth_class, "auth_id", auth_file.stem)
                AuthRegistry.register(auth_id, auth_class)
    
    @staticmethod
    def _scan_channel_extensions(channels_dir: Path, provider_name: str):
        """Scan Channel extensions"""
        for channel_file in channels_dir.glob("*.py"):
            if channel_file.name.startswith("_"):
                continue
            module = import_module_from_path(channel_file)
            if hasattr(module, "ChannelHandler"):
                handler_class = module.ChannelHandler
                channel_type = getattr(handler_class, "channel_type", channel_file.stem)
                ChannelRegistry.register(channel_type, handler_class)
```

### 1.3 Provider Extension Examples

```python
# app/atlasclaw/providers/ldap/auth/ldap.py
from app.atlasclaw.auth.providers.base import AuthProvider

class LDAPAuth(AuthProvider):
    """LDAP authentication provider"""
    
    auth_id = "ldap"  # Identifier
    auth_name = "LDAP"
    
    async def authenticate(self, credential: str) -> AuthResult:
        # LDAP authentication logic
        pass
    
    def provider_name(self) -> str:
        return "ldap"
```

```python
# app/atlasclaw/providers/feishu/channels/feishu.py
from app.atlasclaw.channels.handler import ChannelHandler

class FeishuHandler(ChannelHandler):
    """Feishu channel handler"""
    
    channel_type = "feishu"
    channel_name = "Feishu"
    
    async def start(self, connection, context):
        # Start Feishu connection
        pass
    
    async def send_message(self, connection, outbound):
        # Send Feishu message
        pass
    
    # ... other methods
```

## 2. Auth Extension Design

### 2.1 Current Implementation Review

Current `app/atlasclaw/auth/providers/base.py`:

```python
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credential: str) -> AuthResult: ...
    
    @abstractmethod
    def provider_name(self) -> str: ...
```

### 2.2 Extension Design

Maintain current simple design, add registration mechanism and Provider scanning:

```python
# app/atlasclaw/auth/registry.py
from typing import Type, Dict, Optional, List
from pathlib import Path

class AuthRegistry:
    """Auth provider registration table"""
    
    _providers: Dict[str, Type[AuthProvider]] = {}
    
    @classmethod
    def register(cls, provider_id: str, provider_class: Type[AuthProvider]):
        """Register Auth provider"""
        cls._providers[provider_id] = provider_class
        
    @classmethod
    def get(cls, provider_id: str) -> Optional[Type[AuthProvider]]:
        """Get Auth provider class"""
        return cls._providers.get(provider_id)
    
    @classmethod
    def list_providers(cls) -> List[str]:
        """List all registered providers"""
        return list(cls._providers.keys())
    
    @classmethod
    def scan_providers(cls, providers_dir: Path):
        """Scan auth extensions under providers directory"""
        for provider_path in providers_dir.iterdir():
            if not provider_path.is_dir():
                continue
            
            auth_dir = provider_path / "auth"
            if not auth_dir.exists():
                continue
            
            for auth_file in auth_dir.glob("*.py"):
                if auth_file.name.startswith("_"):
                    continue
                # Dynamically import
                module = import_module_from_path(auth_file)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, AuthProvider) and 
                        attr is not AuthProvider and
                        hasattr(attr, "auth_id")):
                        cls.register(attr.auth_id, attr)
```

### 2.3 Built-in Auth Types

| Type | ID | Description | Location |
|------|-----|-------------|----------|
| OIDC | `oidc` | OpenID Connect | Built-in |
| OAuth2 | `oauth2` | OAuth 2.0 | Built-in |
| API Key | `api_key` | Simple API Key | Built-in |
| SAML | `saml` | SAML 2.0 | Built-in |
| None | `none` | No authentication (dev use) | Built-in |
| LDAP | `ldap` | LDAP authentication | Provider extension |
| AD | `ad` | Active Directory | Provider extension |

### 2.4 Auth Configuration (Global)

Auth configuration is **global**, effective for entire workspace, stored in workspace root's `atlasclaw.json`:

```json
// <workspace>/atlasclaw.json
{
  "auth": {
    "provider": "oidc",
    "config": {
      "issuer_url": "https://auth.example.com",
      "client_id": "atlasclaw",
      "client_secret": "${OIDC_CLIENT_SECRET}"
    }
  }
}
```

**Note**: Auth configuration is workspace-level, all users share the same authentication configuration. This is different from Channel configuration, which is per-user isolated.

## 3. Channel Extension Design

### 3.1 Unified ChannelRegistry

Use a **single ChannelRegistry** to manage all Channels (built-in and extensions):

```python
# app/atlasclaw/channels/registry.py
from typing import Type, Dict, Optional, List, Any
from pathlib import Path
from enum import Enum

class ChannelMode(Enum):
    """Channel working mode"""
    INBOUND = "inbound"      # Receive only (e.g., Webhook)
    OUTBOUND = "outbound"    # Send only (e.g., SMTP)
    BIDIRECTIONAL = "bidirectional"  # Two-way (e.g., WebSocket)

class ChannelRegistry:
    """
    Unified Channel registration table
    
    Manages all types of Channels:
    - Built-in Channels: WebSocket, SSE, REST (AtlasClaw actively listens)
    - Extension Channels: Feishu, Slack, WhatsApp (Driver manages connection)
    """
    
    _handlers: Dict[str, Type[ChannelHandler]] = {}
    _instances: Dict[str, ChannelHandler] = {}  # channel_id -> handler instance
    _connections: Dict[str, ChannelConnection] = {}  # connection_id -> connection
    
    @classmethod
    def register(cls, channel_type: str, handler_class: Type[ChannelHandler]):
        """
        Register Channel Handler
        
        Args:
            channel_type: Channel type identifier, e.g., 'feishu', 'slack', 'websocket'
            handler_class: ChannelHandler subclass
        """
        cls._handlers[channel_type] = handler_class
        
    @classmethod
    def get(cls, channel_type: str) -> Optional[Type[ChannelHandler]]:
        """Get Handler class"""
        return cls._handlers.get(channel_type)
    
    @classmethod
    def list_channels(cls) -> List[str]:
        """List all registered Channel types"""
        return list(cls._handlers.keys())
    
    @classmethod
    def create_instance(
        cls,
        channel_id: str,
        channel_type: str,
        config: Dict[str, Any]
    ) -> Optional[ChannelHandler]:
        """
        Create Channel Handler instance
        
        For built-in Channels (WebSocket/SSE/REST), create instance and register
        For extension Channels, usually managed by Connection
        """
        handler_class = cls._handlers.get(channel_type)
        if not handler_class:
            return None
        
        instance = handler_class(config)
        cls._instances[channel_id] = instance
        return instance
    
    @classmethod
    def get_instance(cls, channel_id: str) -> Optional[ChannelHandler]:
        """Get created Handler instance"""
        return cls._instances.get(channel_id)
    
    @classmethod
    def scan_providers(cls, providers_dir: Path):
        """Scan channel extensions under providers directory"""
        for provider_path in providers_dir.iterdir():
            if not provider_path.is_dir():
                continue
            
            channels_dir = provider_path / "channels"
            if not channels_dir.exists():
                continue
            
            for channel_file in channels_dir.glob("*.py"):
                if channel_file.name.startswith("_"):
                    continue
                # Dynamically import
                module = import_module_from_path(channel_file)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, ChannelHandler) and 
                        attr is not ChannelHandler and
                        hasattr(attr, "channel_type")):
                        cls.register(attr.channel_type, attr)
```

### 3.2 ChannelHandler Interface

Unified ChannelHandler interface, applicable to both built-in and extension Channels:

```python
# app/atlasclaw/channels/handler.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from enum import Enum

class ConnectionStatus(Enum):
    """Connection status"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"

class ChannelHandler(ABC):
    """
    Channel handler base class
    
    Handles all Channel types uniformly:
    - Built-in Channels (WebSocket/SSE/REST): AtlasClaw actively listens for connections
    - Extension Channels (Feishu/Slack): Connect to external platforms
    """
    
    channel_type: str = ""      # Type identifier, e.g., 'feishu', 'websocket'
    channel_name: str = ""      # Display name
    channel_icon: str = ""      # Icon
    channel_mode: ChannelMode = ChannelMode.BIDIRECTIONAL  # Working mode
    
    # ========== Configuration Management ==========
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._status = ConnectionStatus.DISCONNECTED
        self._connection_id: Optional[str] = None
    
    # ========== Lifecycle Management ==========
    
    @abstractmethod
    async def setup(self, connection_config: Dict[str, Any]) -> bool:
        """
        Initialize configuration
        
        - Validate credentials (Token, Key, etc.)
        - Initialize API clients
        - Get platform information
        """
        pass
    
    @abstractmethod
    async def start(self, context: Any) -> bool:
        """
        Start Channel
        
        Built-in Channels: Start server/listener (WebSocket/SSE/HTTP)
        Extension Channels: Establish connection to platform (Webhook/WebSocket/Polling)
        """
        pass
    
    @abstractmethod
    async def stop(self) -> bool:
        """Stop Channel and cleanup resources"""
        pass
    
    async def health_check(self) -> bool:
        """Health check"""
        return self._status == ConnectionStatus.CONNECTED
    
    def get_status(self) -> ConnectionStatus:
        """Get current status"""
        return self._status
    
    # ========== Message Reception (Platform -> AtlasClaw) ==========
    
    @abstractmethod
    async def handle_inbound(
        self, 
        request: Any
    ) -> Optional[InboundMessage]:
        """
        Handle inbound message
        
        Built-in Channels: Handle client connection requests
        Extension Channels: Handle platform Webhook/message push
        
        Args:
            request: Request object (FastAPI Request or connection object)
            
        Returns:
            InboundMessage if valid message
        """
        pass
    
    # ========== Message Sending (AtlasClaw -> Platform) ==========
    
    @abstractmethod
    async def send_message(
        self,
        outbound: OutboundMessage
    ) -> SendResult:
        """
        Send message
        
        Built-in Channels: Send to client via WebSocket/SSE
        Extension Channels: Call platform API to send
        """
        pass
    
    async def send_typing_indicator(
        self,
        chat_id: str,
        duration: float = 5.0
    ) -> bool:
        """Send typing indicator"""
        return False
    
    # ========== Capability Queries ==========
    
    def supports_typing(self) -> bool:
        return False
    
    def supports_media(self) -> bool:
        return False
    
    def supports_thread(self) -> bool:
        return False
```

### 3.3 Built-in Channel Implementations

```python
# app/atlasclaw/channels/handlers/websocket.py
class WebSocketHandler(ChannelHandler):
    """WebSocket Channel - Built-in"""
    
    channel_type = "websocket"
    channel_name = "WebSocket"
    channel_mode = ChannelMode.BIDIRECTIONAL
    
    async def setup(self, config: Dict[str, Any]) -> bool:
        # WebSocket needs no special configuration
        return True
    
    async def start(self, context: Any) -> bool:
        # Start WebSocket server, wait for client connections
        # Register WebSocket route in FastAPI
        self._status = ConnectionStatus.CONNECTED
        return True
    
    async def handle_inbound(
        self, 
        websocket: WebSocket
    ) -> Optional[InboundMessage]:
        # Handle client WebSocket connection
        # Receive message and convert to InboundMessage
        data = await websocket.receive_json()
        return InboundMessage(
            message_id=data["id"],
            sender_id=data["user_id"],
            chat_id=data["session_id"],
            content=data["message"],
            channel_type=self.channel_type,
        )
    
    async def send_message(
        self,
        outbound: OutboundMessage
    ) -> SendResult:
        # Send to client via WebSocket
        # ...
        pass
```

### 3.4 Extension Channel Implementations

```python
# app/atlasclaw/providers/feishu/channels/feishu.py
class FeishuHandler(ChannelHandler):
    """Feishu Channel - Extension"""
    
    channel_type = "feishu"
    channel_name = "Feishu"
    channel_icon = "feishu"
    channel_mode = ChannelMode.BIDIRECTIONAL
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._api: Optional[FeishuAPI] = None
    
    async def setup(self, connection_config: Dict[str, Any]) -> bool:
        """Validate Feishu configuration"""
        app_id = connection_config.get("app_id")
        app_secret = connection_config.get("app_secret")
        
        # Validate Token validity
        self._api = FeishuAPI(app_id, app_secret)
        return await self._api.validate_credentials()
    
    async def start(self, context: Any) -> bool:
        """
        Start Feishu Channel
        
        Webhook mode: No active start, wait for platform push
        WebSocket mode: Establish long connection
        """
        # If WebSocket mode, establish connection
        if self.config.get("mode") == "websocket":
            await self._api.connect_websocket()
        
        self._status = ConnectionStatus.CONNECTED
        return True
    
    async def handle_inbound(
        self, 
        request: Request
    ) -> Optional[InboundMessage]:
        """Handle Feishu Webhook"""
        # 1. Verify signature
        signature = request.headers.get("X-Signature")
        body = await request.body()
        if not self._verify_signature(body, signature):
            return None
        
        # 2. Parse message
        data = await request.json()
        
        # 3. Convert to unified format
        return InboundMessage(
            message_id=data["message"]["message_id"],
            sender_id=data["sender"]["sender_id"]["open_id"],
            sender_name=data["sender"]["nickname"],
            chat_id=data["chat_id"],
            content=data["message"]["content"]["text"],
            channel_type=self.channel_type,
        )
    
    async def send_message(
        self,
        outbound: OutboundMessage
    ) -> SendResult:
        """Send Feishu message"""
        # Convert format and call Feishu API
        result = await self._api.send_message(
            chat_id=outbound.chat_id,
            content=self._format_content(outbound)
        )
        return SendResult(
            success=result.success,
            message_id=result.message_id,
        )
```

### 3.5 Built-in Channel Types

| Type | ID | Transport | Location | Description |
|------|-----|-----------|----------|-------------|
| WebSocket | `websocket` | WebSocket | Built-in | Browser/client connection |
| SSE | `sse` | SSE | Built-in | Server push |
| REST | `rest` | HTTP | Built-in | Callback interface |
| Feishu | `feishu` | Webhook/WebSocket | Provider extension | Feishu bot |
| Slack | `slack` | Webhook/Socket | Provider extension | Slack integration |
| WhatsApp | `whatsapp` | WebSocket | Provider extension | WhatsApp Business |
| DingTalk | `dingtalk` | Webhook | Provider extension | DingTalk bot |

### 3.6 User Channel Configuration Storage

Channel configuration is per-user, stored under workspace's user directory:

```
<workspace>/
└── users/
    └── <user_id>/
        └── channels/
            ├── feishu.json       # User's Feishu connection configuration
            └── slack.json        # User's Slack connection configuration
```

```json
// feishu.json
{
  "version": 1,
  "channel_type": "feishu",
  "updated_at": "2026-03-11T12:00:00Z",
  "connections": [
    {
      "id": "feishu_conn_001",
      "name": "Work Bot",
      "enabled": true,
      "is_default": true,
      "config": {
        "app_id": "cli_xxx",
        "app_secret": "enc:xxxx",
        "verification_token": "enc:xxxx"
      },
      "runtime_state": {
        "status": "connected",
        "last_seen_at": "2026-03-11T12:00:00Z"
      }
    }
  ]
}
```

**Note**: Channel configuration is different from Auth configuration, Channel is per-user isolated, each user can have their own Channel connection configuration.

## 4. Skills (Already Implemented)

`SkillRegistry` is fully implemented, supporting:
- Executable skill registration and execution
- Markdown capability loading (SKILL.md)
- Automatic scanning from providers directory
- Priority management (workspace > user > built-in)

```python
# Already implemented scanning method (in main.py)
providers_dir = Path(__file__).parent / "providers"
if providers_dir.exists():
    for provider_path in providers_dir.iterdir():
        if provider_path.is_dir():
            provider_skills = provider_path / "skills"
            if provider_skills.exists():
                _skill_registry.load_from_directory(str(provider_skills), location="built-in")
```

## 5. Unified Scanning at Startup

```python
# main.py startup flow
def load_extensions():
    """Load all extensions"""
    providers_dir = Path(__file__).parent / "providers"
    
    # 1. Scan Auth extensions
    AuthRegistry.scan_providers(providers_dir)
    
    # 2. Scan Channel extensions (unified registration to ChannelRegistry)
    ChannelRegistry.scan_providers(providers_dir)
    
    # 3. Register built-in Channels
    ChannelRegistry.register("websocket", WebSocketHandler)
    ChannelRegistry.register("sse", SSEHandler)
    ChannelRegistry.register("rest", RESTHandler)
    
    # 4. Scan Skills extensions (already exists)
    for provider_path in providers_dir.iterdir():
        if provider_path.is_dir():
            provider_skills = provider_path / "skills"
            if provider_skills.exists():
                _skill_registry.load_from_directory(str(provider_skills), location="built-in")
```

## 6. Relationship with Existing Components

### 6.1 Configuration Storage Comparison

| Feature | Service Providers | Channel Integrations | Auth Providers |
|----------|-------------------|---------------------|----------------|
| **Purpose** | Enterprise capabilities | Messaging channels | Identity authentication |
| **Config Location** | `<workspace>/atlasclaw.json` | `<workspace>/users/<user_id>/channels/` | `<workspace>/atlasclaw.json` |
| **Scope** | Workspace global | User isolation | Workspace global |
| **Lifecycle** | Application singleton | User-level multiple instances | Request-level |
| **Extension Location** | `providers/<name>/` | `providers/<name>/channels/` | `providers/<name>/auth/` |
| **Loading Method** | Configuration instantiation | Handler registration + scanning | Provider registration + scanning |

### 6.2 Channel Workflow

#### 6.2.1 Current Channel Architecture (Existing)

Current AtlasClaw has implemented basic Channel system:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Current Channel Architecture                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────┐     ┌──────────────────┐     ┌─────────────────┐ │
│  │  WebSocket       │     │  SSE             │     │  REST           │ │
│  │  Handler         │     │  Handler         │     │  Handler        │ │
│  │                  │     │                  │     │                 │ │
│  │ • Browser connection      │     │ • Server push      │     │ • HTTP callback     │ │
│  │ • Real-time bidirectional    │     │ • One-way stream   │     │ • Webhook receive  │ │
│  └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘ │
│           │                        │                        │          │
│           └────────────────────────┼────────────────────────┘          │
│                                    │                                   │
│                                    ▼                                   │
│                         ┌─────────────────────┐                        │
│                         │ ChannelRegistry     │                        │
│                         │                     │                        │
│                         │ • register()        │                        │
│                         │ • get()             │                        │
│                         │ • create_instance() │                        │
│                         └──────────┬──────────┘                        │
│                                    │                                   │
│                                    ▼                                   │
│                         ┌─────────────────────┐                        │
│                         │ Session Manager     │                        │
│                         │                     │                        │
│                         │ • Session creation/recovery      │                        │
│                         │ • Message routing           │                        │
│                         └──────────┬──────────┘                        │
│                                    │                                   │
│                                    ▼                                   │
│                         ┌─────────────────────┐                        │
│                         │ Agent Runner        │                        │
│                         │ + Skills            │                        │
│                         └─────────────────────┘                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Current Channel registration location:**
- `app/atlasclaw/channels/registry.py` - `ChannelRegistry` (unified registration table)
- Built-in Handlers: WebSocket, SSE, REST
- Registered to Registry in `main.py`

**Current workflow:**
1. Client connects to AtlasClaw via WebSocket/SSE/REST
2. `ChannelHandler` receives message, converts to `InboundMessage`
3. `SessionManager` routes to session based on `session_key`
4. `AgentRunner` processes message, calls Skills
5. Response sent back via same `ChannelHandler`

#### 6.2.2 Detailed Message Interaction Flow

**Complete external Channel interaction flow (Feishu as example):**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Message Reception Flow (Platform -> AtlasClaw)                         │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. User sends message                                                             │
│     ┌─────────┐                                                             │
│     │  User   │───Send message in Feishu chat @bot                            │
│     └────┬────┘                                                             │
│          │                                                                  │
│  2. Platform pushes message                                                             │
│          ▼                                                                  │
│     ┌─────────────┐                                                         │
│     │  Feishu     │───Detect message, push to configured Webhook URL                    │
│     │  Server     │    POST /api/channel-hooks/feishu/conn_001               │
│     └──────┬──────┘                                                         │
│            │                                                                │
│  3. AtlasClaw receives message                                                       │
│            ▼                                                                │
│     ┌─────────────────┐                                                     │
│     │  FastAPI        │───Receive HTTP request                                     │
│     │  Webhook Route  │    /api/channel-hooks/{type}/{connection_id}        │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  4. Handler processes message                                                         │
│              ▼                                                              │
│     ┌─────────────────┐                                                     │
│     │  FeishuHandler  │───handle_inbound() called                            │
│     │                 │                                                     │
│     │  1. Verify signature    │───Verify X-Signature to prevent forgery              │
│     │  2. Parse message    │───Parse JSON payload                                  │
│     │  3. Format conversion    │───Convert to InboundMessage                              │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  5. Route message to Agent                                                         │
│              ▼                                                              │
│     ┌─────────────────┐                                                     │
│     │  ChannelManager │───Route message to corresponding Session                              │
│     │                 │                                                     │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  6. Create/get session                                                            │
│              ▼                                                              │
│     ┌─────────────────┐                                                     │
│     │  Session        │───Get Session based on (channel_type, chat_id, user_id) │
│     │  Manager        │    Create new session if not exists                              │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  7. Agent processes message                                                           │
│              ▼                                                              │
│     ┌─────────────────┐                                                     │
│     │  Request        │───Build request context                                      │
│     │  Orchestrator   │    (message, session, user_context)                  │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  8. Execute Skills                                                              │
│              ▼                                                              │
│     ┌─────────────────┐                                                     │
│     │  Agent Runner   │───Call LLM, execute Skills                              │
│     │  + Skills       │    Generate reply content                                       │
│     └────────┬────────┘                                                     │
│              │                                                              │
└──────────────┼──────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Message Sending Flow (AtlasClaw -> Platform)                         │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  9. Prepare reply                                                             │
│     ┌─────────────────┐                                                     │
│     │  OutboundMessage│───Contains reply content, chat_id, format info, etc.                   │
│     │  (reply)        │                                                     │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  10. Handler sends message                                                        │
│              ▼                                                              │
│     ┌─────────────────┐                                                     │
│     │  FeishuHandler  │───send_message() called                              │
│     │                 │                                                     │
│     │  10.1 Format conversion   │───Convert Markdown to Feishu rich text                     │
│     │  10.2 Call API   │───POST /open-apis/message/v4/send/                  │
│     │  10.3 Handle response   │───Get message_id, record send status                       │
│     └────────┬────────┘                                                     │
│              │                                                              │
│  11. User sees reply on platform                                                       │
│              ▼                                                              │
│     ┌─────────┐                                                             │
│     │  User   │───See bot's reply in Feishu                                 │
│     └─────────┘                                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key interaction points explained:**

| Stage | Component | Responsibility |
|-------|-----------|-------------|
| **Reception** | FeishuHandler.handle_inbound() | Verify signature, parse message, format conversion |
| **Routing** | ChannelManager | Route message to correct Session |
| **Processing** | RequestOrchestrator + AgentRunner | Business logic processing, Skills execution |
| **Sending** | FeishuHandler.send_message() | Format conversion, call platform API |

**Message format conversion example:**

```python
# Feishu message format -> InboundMessage
{
    "message_id": "om_123456",
    "sender": {"sender_id": {"open_id": "ou_xxx"}, "nickname": "Zhang San"},
    "chat_id": "oc_xxx",
    "message_type": "text",
    "content": {"text": "@bot hello"},
    "create_time": "1234567890"
}
↓ Convert
InboundMessage(
    message_id="om_123456",
    sender_id="ou_xxx",
    sender_name="Zhang San",
    chat_id="oc_xxx",
    content="@bot hello",
    channel_type="feishu",
    connection_id="feishu_conn_001",
)

# OutboundMessage -> Feishu message format
OutboundMessage(
    content="Hello! How can I help you?",
    chat_id="oc_xxx",
    format="markdown"
)
↓ Convert
{
    "chat_id": "oc_xxx",
    "msg_type": "interactive",
    "card": {
        "elements": [{"tag": "div", "text": {"content": "Hello! How can I help you?"}}]
    }
}
```

#### 6.2.3 Key Differences

| Feature | Built-in Channel | Extension Channel |
|---------|---------------|----------------|
| **Connection Initiator** | AtlasClaw (waits for client connection) | External system (actively connects) |
| **Config Location** | `atlasclaw.json` | `<workspace>/users/<user_id>/channels/` |
| **Management Method** | `ChannelRegistry` unified management | `ChannelRegistry` unified management |
| **Lifecycle** | Connection created on startup | Explicitly configured then started/stopped |
| **User Isolation** | Session-level | Configuration-level (each user has independent config) |

## 7. API Design

### 7.1 Channel Configuration API

```
GET    /api/channels                    # List supported channel types
GET    /api/channels/{type}/schema      # Get configuration form schema
GET    /api/channels/{type}/connections # List user's connections
POST   /api/channels/{type}/connections # Create connection
GET    /api/channels/{type}/connections/{id}
PATCH  /api/channels/{type}/connections/{id}
DELETE /api/channels/{type}/connections/{id}
POST   /api/channels/{type}/connections/{id}/verify
POST   /api/channels/{type}/connections/{id}/enable
POST   /api/channels/{type}/connections/{id}/disable
```

### 7.2 Channel Webhook API

```
POST /api/channel-hooks/{channel_type}/{connection_id}
```

Independent from existing `webhook_dispatch.py` (used for Skills).

## 8. Implementation Recommendations

### 8.1 Directory Structure

#### Code Directory

```
app/atlasclaw/
├── auth/
│   ├── providers/
│   │   ├── base.py          # AuthProvider ABC
│   │   ├── oidc.py          # Built-in OIDC
│   │   ├── oauth2.py        # Built-in OAuth2
│   │   └── api_key.py       # Built-in API Key
│   └── registry.py          # AuthRegistry + scanning
│
├── channels/
│   ├── handler.py           # ChannelHandler ABC (unified interface)
│   ├── registry.py          # ChannelRegistry (unified registration table)
│   ├── manager.py           # ChannelManager (connection management)
│   └── handlers/            # Built-in Handler implementations
│       ├── __init__.py
│       ├── websocket.py     # WebSocket Handler
│       ├── sse.py           # SSE Handler
│       └── rest.py          # REST Handler
├── providers/               # Provider extension directory
│   ├── jira/                # Jira Provider
│   │   ├── __init__.py
│   │   ├── skills/          # Jira Skills
│   │   └── ...
│   ├── feishu/              # Feishu Provider (extension)
│   │   ├── __init__.py
│   │   ├── channels/
│   │   │   └── feishu.py    # Feishu Handler
│   │   └── skills/
│   ├── slack/               # Slack Provider (extension)
│   │   ├── __init__.py
│   │   ├── channels/
│   │   │   └── slack.py
│   │   └── skills/
│   └── ldap/                # LDAP Provider (extension)
│       └── auth/
│           └── ldap.py      # LDAP AuthProvider
└── skills/
    └── registry.py          # SkillRegistry (already exists)
```

#### Workspace Directory Structure

```
<workspace>/
├── atlasclaw.json           # Global configuration (Auth, Service Providers)
├── .atlasclaw/              # System directory
│   ├── agents/              # Agent definitions
│   ├── providers/           # Provider configuration
│   └── channels/            # Channel configuration (code)
└── users/                   # User directory
    └── <user_id>/           # User-isolated data
        ├── atlasclaw.json   # User configuration
        ├── sessions/        # Session data
        ├── memory/          # Long-term memory
        └── channels/        # Channel configuration (user-isolated)
            ├── feishu.json
            └── slack.json
```

**Configuration storage rules:**
- **Auth**: `<workspace>/atlasclaw.json` - Global, all users share same authentication configuration
- **Channel**: `<workspace>/users/<user_id>/channels/*.json` - User-isolated
- **Service Providers**: `<workspace>/atlasclaw.json` - Global
- **Extension Location**: `providers/<name>/` - For Auth, Channels, and Skills
- **Loading Method**: Configuration instantiation | Handler registration + scanning | Provider registration + scanning

### 8.2 Implementation Phases

1. **Phase 1**: Auth Registry + Provider scanning mechanism
2. **Phase 2**: ChannelRegistry (unified registration table) + ChannelHandler interface
3. **Phase 3**: Built-in Channels moved to ChannelHandler
4. **Phase 4**: Channel Manager + Store + REST API
5. **Phase 5**: Feishu Handler (as Provider extension)
6. **Phase 6**: Slack/WhatsApp Handlers

## 9. Comparison with OpenClaw

| Feature | OpenClaw | AtlasClaw (This Design) |
|----------|----------|-------------------|
| Plugin Architecture | Unified Plugin System | Separated Registry + Provider Scanning |
| Channel | `ChannelPlugin` inherits | `ChannelHandler` unified interface |
| Registry | Multiple (AdapterRegistry + PluginRegistry) | **Single ChannelRegistry** |
| Auth | `AuthAdapter` inherits | `AuthProvider` + Provider scanning |
| Skills | SDK registration | Directory scanning (already implemented) |
| Discovery | Directory scanning + SDK | **Unified Provider directory scanning** |
| User Isolation | No | Channel configuration user-isolated |
| Config Storage | Global | Auth/Provider global, Channel user directory |
| Extension Location | `plugins/<name>/` | `providers/<name>/` |

## 10. Advantages

1. **Single Registry**: Use one ChannelRegistry to manage all Channels, simplifying architecture
2. **Unified Interface**: Built-in and extension Channels use same ChannelHandler interface
3. **Simple**: No unified Plugin abstraction, each component maintains independent interface
4. **Flexible**: Auth as simple function, Channel unified interface, Skills maintain existing implementation
5. **Extensible**: Add auth/channels/skills under providers directory
6. **Backward Compatible**: Skills' existing scanning mechanism remains unchanged

---

*This design is based on current AtlasClaw implementation, deprecating the unified Plugin architecture in favor of a unified Provider directory scanning mechanism and single ChannelRegistry.*
