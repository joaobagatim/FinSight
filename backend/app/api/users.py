"""Own-user credential mutations: live access, session-bound CSRF and reauthentication."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.dependencies import get_current_user
from app.api.session_auth import SessionRequest, security
from app.core.csrf import CsrfRejected
from app.schemas.session_auth import ProfileResponse
from app.schemas.users import PasswordChangeInput, ProfileUpdateInput
from app.services.session_types import AuthContext

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=ProfileResponse)
def profile(user: Annotated[AuthContext, Depends(get_current_user)]):
    return ProfileResponse(id=user.user_id, name=user.name, email=user.email)


@router.patch("/me", status_code=204, response_class=Response)
def update_profile(
    data: ProfileUpdateInput,
    context: Annotated[SessionRequest, Depends(security)],
    user: Annotated[AuthContext, Depends(get_current_user)],
):
    binding = context.binding()
    if binding != user.session_id:
        raise CsrfRejected()
    context.verify(binding)
    slots = context.request.app.state.registration_limits.hash_slots
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Authentication limit reached", headers={"Retry-After": "1"})
    try:
        email_changed = context.service.update_profile(context.values["access"], data)
    finally:
        slots.release()
    response = Response(status_code=204)
    if email_changed:
        context.cookies.clear(response)
    return response


@router.post("/me/change-password", status_code=204, response_class=Response)
def change_password(
    data: PasswordChangeInput,
    context: Annotated[SessionRequest, Depends(security)],
    user: Annotated[AuthContext, Depends(get_current_user)],
):
    binding = context.binding()
    if binding != user.session_id:
        raise CsrfRejected()
    context.verify(binding)
    slots = context.request.app.state.registration_limits.hash_slots
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Authentication limit reached", headers={"Retry-After": "1"})
    try:
        context.service.change_password(
            context.values["access"], data.current_password, data.new_password
        )
    finally:
        slots.release()
    response = Response(status_code=204)
    context.cookies.clear(response)
    return response
