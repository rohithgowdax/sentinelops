"""
ActionProvider protocol definition and re-exports.
"""
from __future__ import annotations

from sentinelops.domain.contracts.protocols import (
    ActionProvider,
    ActionValidationResult,
)

__all__ = ["ActionProvider", "ActionValidationResult"]
