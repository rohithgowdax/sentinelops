"""
AWS Integration Adapters for SentinelOps (Slice 5C).
"""
from sentinelops.integrations.aws.gateway import AgentCoreGatewayAdapter
from sentinelops.integrations.aws.runtime import AgentCoreRuntimeAdapter

__all__ = [
    "AgentCoreGatewayAdapter",
    "AgentCoreRuntimeAdapter",
]
