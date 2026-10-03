"""
FastAPI REST Router for SentinelOps Approval API.

Exposes endpoints for listing, viewing, approving, and rejecting remediation action requests.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from sentinelops.approval.service import ApprovalRequest, ApprovalService, ApprovalStatus
from sentinelops.domain.models.policy import ActorContext, ActorRole

router = APIRouter(prefix="/approvals", tags=["approvals"])

# Module-level singleton default service for API injection
_global_approval_service = ApprovalService()


def get_approval_service() -> ApprovalService:
    return _global_approval_service


class ApprovalDecisionPayload(BaseModel):
    actor_id: str = Field(..., description="Unique ID of the approving/rejecting operator")
    actor_role: ActorRole = Field(..., description="Role tier of the operator")
    reason: str = Field(default="Reviewed by operator", description="Audit explanation")


@router.get("", response_model=list[ApprovalRequest])
async def list_approvals(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    service: ApprovalService = Depends(get_approval_service),
) -> list[ApprovalRequest]:
    """List pending or resolved remediation approvals."""
    return service.list_approvals(status=status_filter)


@router.get("/{action_id}", response_model=ApprovalRequest)
async def get_approval(
    action_id: str,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalRequest:
    """Retrieve approval details for an action ID."""
    app = service.get_approval(action_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request for action '{action_id}' not found.",
        )
    return app


@router.post("/{action_id}/approve", response_model=ApprovalRequest)
async def approve_action(
    action_id: str,
    payload: ApprovalDecisionPayload,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalRequest:
    """Approve a pending high-risk action request with authenticated actor credentials."""
    actor = ActorContext(actor_id=payload.actor_id, role=payload.actor_role)
    ok, msg, app = service.approve(action_id, actor, comment=payload.reason)
    if not ok:
        if app is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        if "Unauthorized" in msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return app


@router.post("/{action_id}/reject", response_model=ApprovalRequest)
async def reject_action(
    action_id: str,
    payload: ApprovalDecisionPayload,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalRequest:
    """Reject a pending action request."""
    actor = ActorContext(actor_id=payload.actor_id, role=payload.actor_role)
    ok, msg, app = service.reject(action_id, actor, reason=payload.reason)
    if not ok:
        if app is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return app
