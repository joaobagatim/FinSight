"""Public registration; login and session issuance are separate future endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.schemas.auth import RegistrationInput, RegistrationResponse
from app.services.registration import RegistrationUnavailable, register_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegistrationResponse,
    responses={
        413: {"description": "Body too large"},
        415: {"description": "JSON required"},
        422: {"description": "Invalid data; input is never echoed"},
        429: {"description": "Resource limit reached; see Retry-After"},
        503: {"description": "Registration temporarily unavailable"},
    },
)
def register(
    data: RegistrationInput,
    request: Request,
    session: Annotated[Session | None, Depends(get_session)],
):
    if session is None:
        raise RegistrationUnavailable()
    slots = request.app.state.registration_limits.hash_slots
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Registration limit reached", headers={"Retry-After": "1"})
    try:
        register_user(session, data)
    finally:
        slots.release()
    return RegistrationResponse()
