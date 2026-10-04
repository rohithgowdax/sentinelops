"""
Change & Deployment MCP Server for SentinelOps (Revision 2026-07-28).

Exposes read-only deployment, release, and configuration change history:
- `list_recent_changes`: Git commits, image rollouts, and configuration changes for a service.
- `get_deployment`: Current active deployment specification, replica count, and health.
- `get_resource_version`: Active image version, hash, and previous known-stable version.
- Resource: `sentinel://deployments/{service_id}`.

Architectural Rule:
Exposes read-only change tracking capabilities.
Does NOT expose write or mutation operations (mutations belong strictly to Remediation MCP Server).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sentinelops.mcp.protocol import (
    ProtocolMetadata,
    ResourceContent,
    ResourceDefinition,
    ToolDefinition,
)
from sentinelops.mcp.server import MCPServer

logger = logging.getLogger(__name__)


def create_change_mcp_server(
    server_name: str = "sentinelops-change",
) -> MCPServer:
    """Factory creating configured Change / Deployment MCP Server."""
    server = MCPServer(
        name=server_name,
        version="1.0.0",
        description="SentinelOps Read-Only Change & Deployment Tracking MCP Server",
    )

    # 1. Tool: list_recent_changes
    tool_list_changes = ToolDefinition(
        name="list_recent_changes",
        description="List recent code deployments, configuration tweaks, and pull requests for a service.",
        inputSchema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Target service identifier, e.g. 'payments-service'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default: 5)",
                },
            },
            "required": ["service"],
        },
        is_mutation=False,
    )

    async def handle_list_changes(arguments: dict[str, Any], metadata: ProtocolMetadata) -> dict[str, Any]:
        service = arguments["service"]
        limit = arguments.get("limit", 5)

        changes = [
            {
                "change_id": "CHG-2026-1049",
                "change_type": "deployment",
                "service": service,
                "version": "1.8.3",
                "previous_version": "1.8.2",
                "deployed_at": "2026-10-04T19:45:00Z",
                "author": "ci-cd-bot",
                "commit_sha": "a1b2c3d4",
                "summary": "Upgrade payment processor library to v2.4.0",
            },
            {
                "change_id": "CHG-2026-1048",
                "change_type": "config_update",
                "service": service,
                "deployed_at": "2026-10-04T17:15:00Z",
                "author": "sre-lead",
                "summary": "Increase db connection pool max_size from 20 to 50",
            },
        ]
        return {
            "service": service,
            "environment": metadata.environment,
            "total_changes": len(changes),
            "changes": changes[:limit],
        }

    server.register_tool(tool_list_changes, handle_list_changes)

    # 2. Tool: get_deployment
    tool_get_deployment = ToolDefinition(
        name="get_deployment",
        description="Get current deployment status, replica counts, and rollout state for a service.",
        inputSchema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Target service identifier",
                },
            },
            "required": ["service"],
        },
        is_mutation=False,
    )

    async def handle_get_deployment(arguments: dict[str, Any], metadata: ProtocolMetadata) -> dict[str, Any]:
        service = arguments["service"]
        return {
            "service": service,
            "environment": metadata.environment,
            "active_version": "1.8.3",
            "desired_replicas": 4,
            "available_replicas": 4,
            "rollout_status": "complete",
            "last_updated": "2026-10-04T19:48:30Z",
        }

    server.register_tool(tool_get_deployment, handle_get_deployment)

    # 3. Tool: get_resource_version
    tool_get_version = ToolDefinition(
        name="get_resource_version",
        description="Query current active container image, git SHA, and previous known-stable release.",
        inputSchema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Target service identifier",
                },
            },
            "required": ["service"],
        },
        is_mutation=False,
    )

    async def handle_get_version(arguments: dict[str, Any], metadata: ProtocolMetadata) -> dict[str, Any]:
        service = arguments["service"]
        return {
            "service": service,
            "environment": metadata.environment,
            "current_version": "1.8.3",
            "stable_version": "1.8.2",
            "git_commit": "a1b2c3d4e5f6",
            "image_digest": "sha256:7f9b8c6a2e4d",
        }

    server.register_tool(tool_get_version, handle_get_version)

    # Resource: sentinel://deployments/{service_id}
    res_deployment = ResourceDefinition(
        uri="sentinel://deployments/{service_id}",
        name="Service Deployment State",
        description="Full deployment specification and release metadata",
    )

    async def handle_deployment_resource(uri: str, metadata: ProtocolMetadata) -> ResourceContent:
        service_id = uri.split("/")[-1]
        data = {
            "service_id": service_id,
            "environment": metadata.environment,
            "active_version": "1.8.3",
            "stable_version": "1.8.2",
            "desired_replicas": 4,
        }
        return ResourceContent(uri=uri, text=json.dumps(data))

    server.register_resource(res_deployment, handle_deployment_resource)

    return server
