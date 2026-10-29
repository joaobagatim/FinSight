"""Cookie-only authentication with signed pre-login/session CSRF protection."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user, get_session_service
from app.core.auth_cookies import AuthCookies
from app.core.csrf import CsrfRejected, CsrfService
from app.schemas.session_auth import CsrfResponse, EmptyInput, LoginInput, ProfileResponse
from app.services.session_types import AuthContext
from app.services.sessions import AuthenticationDenied, SessionBindingMismatch, SessionService

router = APIRouter(prefix="/api/v1/auth", tags=["session"])


class SessionRequest:
    def __init__(self, request: Request, service: SessionService):
        self.request = request
        self.service = service
        self.settings = request.app.state.settings
        self.csrf = CsrfService(self.settings)
        self.csrf.check_origin(request.headers.get("origin"))
        self.cookies = AuthCookies(self.settings, request)
        self.values = self.cookies.read()

    def binding(self):
        if not (self.values.get("refresh") or self.values.get("access")):
            return None
        try:
            return self.service.csrf_binding(
                refresh=self.values.get("refresh"), access=self.values.get("access")
            )
        except SessionBindingMismatch:
            raise
        except AuthenticationDenied:
            return None

    def verify(self, binding=None):
        if binding is None:
            binding = self.values.get("preauth")
            if binding is None:
                raise CsrfRejected()
            purpose = "preauth"
        else:
            purpose = "session"
        self.csrf.verify(
            self.values.get("csrf"),
            self.request.headers.get("x-csrf-token"),
            purpose=purpose,
            binding=binding,
        )

    def set_csrf(self, response: Response, purpose, binding):
        token = self.csrf.issue(purpose, binding)
        expiry = datetime.now(UTC) + timedelta(seconds=self.settings.auth_csrf_ttl_seconds)
        self.cookies.set_csrf(response, token, expires_at=expiry)
        return token


def security(request: Request, service: Annotated[SessionService, Depends(get_session_service)]):
    return SessionRequest(request, service)


@router.post("/csrf", response_model=CsrfResponse)
def bootstrap(
    _data: EmptyInput, context: Annotated[SessionRequest, Depends(security)], response: Response
):
    if context.request.headers.get("x-csrf-bootstrap") != "1":
        raise CsrfRejected()
    binding = context.binding()
    if binding is None:
        context.cookies.clear(response)
        binding = context.csrf.new_preauth_context()
        context.cookies.set_preauth(
            response,
            binding,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=context.settings.auth_csrf_ttl_seconds),
        )
        token = context.set_csrf(response, "preauth", binding)
    else:
        context.cookies.clear(response, kinds=("preauth",))
        token = context.set_csrf(response, "session", binding)
    return CsrfResponse(csrf_token=token.get_secret_value())


@router.post("/login", status_code=204, response_class=Response)
def login(data: LoginInput, context: Annotated[SessionRequest, Depends(security)]):
    if context.binding() is not None:
        raise HTTPException(409, "Log out before starting another session")
    context.verify()
    slots = context.request.app.state.registration_limits.hash_slots
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Authentication limit reached", headers={"Retry-After": "1"})
    try:
        grant = context.service.login(data.email, data.password)
    finally:
        slots.release()
    response = Response(status_code=204)
    context.cookies.clear(response)
    context.cookies.set_grant(response, grant)
    context.set_csrf(response, "session", grant.context.session_id)
    return response


@router.post("/refresh", status_code=204, response_class=Response)
def refresh(_data: EmptyInput, context: Annotated[SessionRequest, Depends(security)]):
    binding = context.binding()
    context.verify(binding)
    try:
        if binding is None or "refresh" not in context.values:
            raise AuthenticationDenied()
        grant = context.service.refresh(context.values["refresh"])
    except AuthenticationDenied:
        response = JSONResponse({"detail": "Authentication denied"}, status_code=401)
        context.cookies.clear(response)
        return response
    response = Response(status_code=204)
    context.cookies.set_grant(response, grant)
    return response


@router.post("/logout", status_code=204, response_class=Response)
def logout(_data: EmptyInput, context: Annotated[SessionRequest, Depends(security)]):
    binding = context.binding()
    context.verify(binding)
    if binding is not None:
        if "refresh" in context.values:
            context.service.revoke_by_refresh(context.values["refresh"])
        elif "access" in context.values:
            context.service.revoke_by_access(context.values["access"])
    response = Response(status_code=204)
    context.cookies.clear(response)
    return response


@router.get("/me", response_model=ProfileResponse)
def me(user: Annotated[AuthContext, Depends(get_current_user)]):
    return ProfileResponse(id=user.user_id, name=user.name, email=user.email)
