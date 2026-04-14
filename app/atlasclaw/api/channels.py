# -*- coding: utf-8 -*-
"""Channel management API routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlasclaw.auth.guards import (
    AuthorizationContext,
    ensure_any_permission,
    ensure_permission,
    get_authorization_context,
)
from app.atlasclaw.channels.manager import ChannelManager
from app.atlasclaw.channels.registry import ChannelRegistry
from app.atlasclaw.core.user_provider_bindings import (
    build_provider_binding_options,
    build_provider_binding_runtime_context,
    parse_provider_binding,
)
from app.atlasclaw.db import get_db_session_dependency as get_db_session
from app.atlasclaw.db.orm.channel_config import ChannelConfigService, _decrypt_config
from app.atlasclaw.db.schemas import ChannelCreate, ChannelUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels", tags=["channels"])

# Global channel manager instance (will be set during app startup)
_channel_manager: Optional[ChannelManager] = None
VALIDATION_TIMEOUT_SECONDS = 3.2


def _normalize_channel_config(
    user_id: str,
    config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate and normalize generic channel config extensions."""
    normalized_config: Dict[str, Any] = dict(config or {})
    provider_type = str(normalized_config.get("provider_type", "") or "").strip().lower()
    provider_binding = str(normalized_config.get("provider_binding", "") or "").strip()

    normalized_config.pop("provider_type", None)

    if not provider_binding:
        normalized_config.pop("provider_binding", None)
        return normalized_config

    parsed_binding = parse_provider_binding(provider_binding)
    if parsed_binding is None:
        normalized_config.pop("provider_binding", None)
        return normalized_config

    resolved_provider_type, _ = parsed_binding
    if provider_type and provider_type != resolved_provider_type:
        provider_binding = f"{resolved_provider_type}/{parsed_binding[1]}"

    build_provider_binding_runtime_context(user_id, provider_binding)
    normalized_config["provider_binding"] = provider_binding
    return normalized_config


def _expand_channel_config_for_response(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Expose helper provider fields for channel edit forms."""
    expanded_config: Dict[str, Any] = dict(config or {})
    provider_binding = str(expanded_config.get("provider_binding", "") or "").strip()
    if not provider_binding:
        expanded_config.pop("provider_type", None)
        return expanded_config

    parsed_binding = parse_provider_binding(provider_binding)
    if parsed_binding is None:
        expanded_config.pop("provider_type", None)
        return expanded_config

    provider_type, _ = parsed_binding
    expanded_config["provider_type"] = provider_type
    return expanded_config


def _augment_channel_schema(
    schema: Optional[Dict[str, Any]],
    *,
    user_id: str,
) -> Dict[str, Any]:
    """Inject generic provider-binding fields into channel schemas."""
    base_schema = dict(schema or {})
    properties = dict(base_schema.get("properties") or {})
    provider_options = build_provider_binding_options(user_id)

    if provider_options:
        provider_type_options: list[str] = []
        provider_type_labels: Dict[str, str] = {}
        options_by_provider: Dict[str, List[Dict[str, str]]] = {}

        for item in provider_options:
            option_provider_type = str(item["provider_type"] or "").strip().lower()
            option_instance_name = str(item["instance_name"] or "").strip()
            option_value = str(item["value"] or "").strip()
            if not option_provider_type or not option_instance_name or not option_value:
                continue

            if option_provider_type not in provider_type_labels:
                provider_type_options.append(option_provider_type)
                provider_label = str(item["label"] or option_provider_type).split("/", 1)[0].strip()
                provider_type_labels[option_provider_type] = provider_label or option_provider_type

            options_by_provider.setdefault(option_provider_type, []).append(
                {
                    "value": option_value,
                    "label": option_instance_name,
                }
            )

        provider_field: Dict[str, Any] = {
            "type": "string",
            "title": "Authentication Method",
            "description": (
                "Choose which authentication configuration this channel should use."
            ),
            "enum": provider_type_options,
            "enumLabels": provider_type_labels,
        }

        binding_field: Dict[str, Any] = {
            "type": "string",
            "title": "Authentication Instance",
            "description": (
                "Choose one configured authentication instance under the selected authentication method."
            ),
            "enum": [item["value"] for item in provider_options],
            "enumLabels": {
                item["value"]: item["instance_name"]
                for item in provider_options
            },
            "optionsByProvider": options_by_provider,
        }

        ordered_properties: Dict[str, Any] = {}
        if "connection_mode" in properties:
            ordered_properties["connection_mode"] = properties["connection_mode"]

        ordered_properties["provider_type"] = provider_field
        ordered_properties["provider_binding"] = binding_field

        for field_name, field_schema in properties.items():
            if field_name == "connection_mode":
                continue
            ordered_properties[field_name] = field_schema

        properties = ordered_properties

    base_schema["properties"] = properties
    return base_schema


def get_channel_manager() -> ChannelManager:
    """Get channel manager instance."""
    if _channel_manager is None:
        raise HTTPException(status_code=500, detail="Channel manager not initialized")
    return _channel_manager


def set_channel_manager(manager: ChannelManager) -> None:
    """Set channel manager instance."""
    global _channel_manager
    _channel_manager = manager


def get_current_user_id(request: Request) -> str:
    """Get current user ID from request.
    
    For now, returns a default user. In production, this would
    extract user info from authentication.
    """
    user_info = getattr(request.state, "user_info", None)
    if user_info is not None and getattr(user_info, "user_id", None):
        return str(user_info.user_id)
    return request.headers.get("X-User-Id", "default")


# Request/Response Models

class ConnectionCreateRequest(BaseModel):
    """Request model for creating a connection."""
    name: str
    config: Dict[str, Any] = {}
    enabled: bool = True
    is_default: bool = False


class ConnectionUpdateRequest(BaseModel):
    """Request model for updating a connection."""
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None


class ConnectionResponse(BaseModel):
    """Response model for a connection."""
    id: str
    name: str
    channel_type: str
    config: Dict[str, Any]
    enabled: bool
    is_default: bool
    runtime_status: str = "disconnected"  # connected/disconnected/connecting/error


class ChannelTypeResponse(BaseModel):
    """Response model for a channel type."""
    type: str
    name: str
    icon: Optional[str] = None
    mode: str
    connection_count: int = 0


class ValidationResponse(BaseModel):
    """Response model for config validation."""
    valid: bool
    errors: List[str] = []


class ConfigValidationRequest(BaseModel):
    """Request model for config validation without saving."""
    config: Dict[str, Any]


# Routes

@router.get("")
async def list_channel_types(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> List[ChannelTypeResponse]:
    """List all available channel types with connection counts.
    
    Returns:
        List of channel types with their info
    """
    ensure_permission(authz, "channels.view", detail="Missing permission: channels.view")
    user_id = authz.user.user_id
    channels = ChannelRegistry.list_channels()
    
    result = []
    for channel in channels:
        # Count connections for this channel type from database
        connections, _ = await ChannelConfigService.list_all(
            session, user_id=user_id, channel_type=channel["type"]
        )
        
        result.append(ChannelTypeResponse(
            type=channel["type"],
            name=channel.get("name", channel["type"]),
            icon=channel.get("icon"),
            mode=channel.get("mode", "bidirectional"),
            connection_count=len(connections)
        ))
    
    return result


@router.get("/{channel_type}/schema")
async def get_channel_schema(
    channel_type: str,
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> Dict[str, Any]:
    """Get configuration schema for a channel type.
    
    Args:
        channel_type: Channel type identifier
        
    Returns:
        JSON Schema for channel configuration
    """
    ensure_permission(authz, "channels.view", detail="Missing permission: channels.view")
    handler_class = ChannelRegistry.get(channel_type)
    if not handler_class:
        raise HTTPException(status_code=404, detail=f"Channel type not found: {channel_type}")
    
    # Create temporary instance to get schema
    try:
        handler = handler_class({})
        return _augment_channel_schema(
            handler.describe_schema(),
            user_id=authz.user.user_id,
        )
    except Exception as e:
        logger.error(f"Failed to get schema for {channel_type}: {e}")
        return {
            "type": "object",
            "properties": {},
            "required": []
        }


@router.get("/{channel_type}/connections")
async def list_connections(
    channel_type: str,
    request: Request,
    manager: ChannelManager = Depends(get_channel_manager),
    session: AsyncSession = Depends(get_db_session),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> Dict[str, Any]:
    """List all connections for a channel type.
    
    Args:
        channel_type: Channel type identifier
        
    Returns:
        List of connections with runtime status
    """
    ensure_permission(authz, "channels.view", detail="Missing permission: channels.view")
    user_id = authz.user.user_id
    
    handler_class = ChannelRegistry.get(channel_type)
    if not handler_class:
        raise HTTPException(status_code=404, detail=f"Channel type not found: {channel_type}")
    
    connections = await ChannelConfigService.list_by_user_and_type(
        session, user_id, channel_type
    )
    
    # Build response with runtime status
    result = []
    for conn in connections:
        conn_data = ChannelConfigService.to_channel_config(conn)
        conn_data["config"] = _expand_channel_config_for_response(conn_data.get("config"))
        # Get runtime status from channel manager
        runtime_status = manager.get_connection_runtime_status(conn.id)
        conn_data["runtime_status"] = runtime_status
        result.append(conn_data)
    
    return {
        "channel_type": channel_type,
        "connections": result
    }


@router.post("/{channel_type}/connections")
async def create_connection(
    channel_type: str,
    data: ConnectionCreateRequest,
    request: Request,
    manager: ChannelManager = Depends(get_channel_manager),
    session: AsyncSession = Depends(get_db_session),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> ConnectionResponse:
    """Create a new channel connection.
    
    Args:
        channel_type: Channel type identifier
        data: Connection data
        
    Returns:
        Created connection
    """
    ensure_permission(authz, "channels.create", detail="Missing permission: channels.create")
    user_id = authz.user.user_id
    
    handler_class = ChannelRegistry.get(channel_type)
    if not handler_class:
        raise HTTPException(status_code=404, detail=f"Channel type not found: {channel_type}")

    try:
        normalized_config = _normalize_channel_config(user_id, data.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Create channel config in database
    channel_data = ChannelCreate(
        user_id=user_id,
        name=data.name,
        type=channel_type,
        config=normalized_config,
        is_active=data.enabled,
        is_default=data.is_default,
    )
    
    channel = await ChannelConfigService.create(session, channel_data)
    
    # Decrypt config for response
    config = _expand_channel_config_for_response(_decrypt_config(channel.config))
    
    # Auto-start connection if enabled
    if channel.is_active:
        logger.info(f"Auto-starting new connection: {user_id}/{channel_type}/{channel.id}")
        asyncio.create_task(
            manager._background_initialize(user_id, channel_type, channel.id)
        )

    return ConnectionResponse(
        id=channel.id,
        name=channel.name,
        channel_type=channel.type,
        config=config,
        enabled=channel.is_active,
        is_default=channel.is_default,
    )


@router.patch("/{channel_type}/connections/{connection_id}")
async def update_connection(
    channel_type: str,
    connection_id: str,
    data: ConnectionUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> ConnectionResponse:
    """Update an existing channel connection.
    
    Args:
        channel_type: Channel type identifier
        connection_id: Connection identifier
        data: Update data
        
    Returns:
        Updated connection
    """
    ensure_permission(authz, "channels.edit", detail="Missing permission: channels.edit")
    user_id = authz.user.user_id
    
    channel = await ChannelConfigService.get_by_id(session, connection_id)
    if not channel or channel.user_id != user_id or channel.type != channel_type:
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
    
    # Build update data
    update_data = ChannelUpdate()
    if data.name is not None:
        update_data.name = data.name
    if data.config is not None:
        try:
            update_data.config = _normalize_channel_config(user_id, data.config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if data.enabled is not None:
        update_data.is_active = data.enabled
    if data.is_default is not None:
        update_data.is_default = data.is_default
    
    channel = await ChannelConfigService.update(session, connection_id, update_data)
    
    # Decrypt config for response
    config = _expand_channel_config_for_response(_decrypt_config(channel.config))
    
    return ConnectionResponse(
        id=channel.id,
        name=channel.name,
        channel_type=channel.type,
        config=config,
        enabled=channel.is_active,
        is_default=channel.is_default,
    )


@router.delete("/{channel_type}/connections/{connection_id}")
async def delete_connection(
    channel_type: str,
    connection_id: str,
    request: Request,
    manager: ChannelManager = Depends(get_channel_manager),
    session: AsyncSession = Depends(get_db_session),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> JSONResponse:
    """Delete a channel connection.
    
    Args:
        channel_type: Channel type identifier
        connection_id: Connection identifier
        
    Returns:
        Success response
    """
    ensure_permission(authz, "channels.delete", detail="Missing permission: channels.delete")
    user_id = authz.user.user_id
    
    # Verify ownership
    channel = await ChannelConfigService.get_by_id(session, connection_id)
    if not channel or channel.user_id != user_id or channel.type != channel_type:
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
    
    # Stop connection if active
    await manager.stop_connection(user_id, channel_type, connection_id)
    
    # Delete from database
    if not await ChannelConfigService.delete(session, connection_id):
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
    
    return JSONResponse(content={"status": "ok", "message": "Connection deleted"})


@router.post("/{channel_type}/validate-config")
async def validate_config(
    channel_type: str,
    data: ConfigValidationRequest,
    request: Request,
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> ValidationResponse:
    """Validate channel configuration without saving to database.
    
    Args:
        channel_type: Channel type identifier
        data: Configuration data to validate
        
    Returns:
        Validation result
    """
    ensure_any_permission(
        authz,
        ("channels.create", "channels.edit"),
        detail="Missing permission: channels.create or channels.edit",
    )
    
    handler_class = ChannelRegistry.get(channel_type)
    if not handler_class:
        raise HTTPException(status_code=404, detail=f"Channel type not found: {channel_type}")

    try:
        normalized_config = _normalize_channel_config(authz.user.user_id, data.config)
    except ValueError as exc:
        return ValidationResponse(valid=False, errors=[str(exc)])

    try:
        handler = handler_class(normalized_config)
        result = await asyncio.wait_for(
            handler.validate_config(normalized_config),
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
        return ValidationResponse(valid=result.valid, errors=result.errors)
    except asyncio.TimeoutError:
        logger.warning("Config validation timed out for %s", channel_type)
        return ValidationResponse(
            valid=False,
            errors=[f"Validation timed out after {int(VALIDATION_TIMEOUT_SECONDS)} seconds"],
        )
    except Exception as e:
        logger.error(f"Config validation failed for {channel_type}: {e}")
        return ValidationResponse(valid=False, errors=[str(e)])


@router.post("/{channel_type}/connections/{connection_id}/verify")
async def verify_connection(
    channel_type: str,
    connection_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> ValidationResponse:
    """Verify a connection's configuration.
    
    Args:
        channel_type: Channel type identifier
        connection_id: Connection identifier
        
    Returns:
        Validation result
    """
    ensure_permission(authz, "channels.edit", detail="Missing permission: channels.edit")
    user_id = authz.user.user_id
    
    channel = await ChannelConfigService.get_by_id(session, connection_id)
    if not channel or channel.user_id != user_id or channel.type != channel_type:
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
    
    handler_class = ChannelRegistry.get(channel_type)
    if not handler_class:
        raise HTTPException(status_code=404, detail=f"Channel type not found: {channel_type}")
    
    # Create handler instance and validate
    try:
        config = _decrypt_config(channel.config)
        try:
            normalized_config = _normalize_channel_config(user_id, config)
        except ValueError as exc:
            return ValidationResponse(valid=False, errors=[str(exc)])

        handler = handler_class(normalized_config)
        result = await asyncio.wait_for(
            handler.validate_config(normalized_config),
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
        return ValidationResponse(valid=result.valid, errors=result.errors)
    except asyncio.TimeoutError:
        logger.warning("Connection verification timed out for %s", connection_id)
        return ValidationResponse(
            valid=False,
            errors=[f"Validation timed out after {int(VALIDATION_TIMEOUT_SECONDS)} seconds"],
        )
    except Exception as e:
        logger.error(f"Validation failed for {connection_id}: {e}")
        return ValidationResponse(valid=False, errors=[str(e)])


@router.post("/{channel_type}/connections/{connection_id}/enable")
async def enable_connection(
    channel_type: str,
    connection_id: str,
    request: Request,
    manager: ChannelManager = Depends(get_channel_manager),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> JSONResponse:
    """Enable a channel connection.
    
    Args:
        channel_type: Channel type identifier
        connection_id: Connection identifier
        
    Returns:
        Success response
    """
    ensure_permission(authz, "channels.edit", detail="Missing permission: channels.edit")
    user_id = authz.user.user_id
    
    if not await manager.enable_connection(user_id, channel_type, connection_id):
        raise HTTPException(status_code=500, detail="Failed to enable connection")
    
    return JSONResponse(content={"status": "ok", "message": "Connection enabled, initializing in background"})


@router.post("/{channel_type}/connections/{connection_id}/disable")
async def disable_connection(
    channel_type: str,
    connection_id: str,
    request: Request,
    manager: ChannelManager = Depends(get_channel_manager),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> JSONResponse:
    """Disable a channel connection.
    
    Args:
        channel_type: Channel type identifier
        connection_id: Connection identifier
        
    Returns:
        Success response
    """
    ensure_permission(authz, "channels.edit", detail="Missing permission: channels.edit")
    user_id = authz.user.user_id
    
    if not await manager.disable_connection(user_id, channel_type, connection_id):
        raise HTTPException(status_code=500, detail="Failed to disable connection")
    
    return JSONResponse(content={"status": "ok", "message": "Connection disabled"})
