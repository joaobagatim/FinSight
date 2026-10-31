"""Application factory; importing this module does not load local settings."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import PlainTextResponse

from app.api.auth import router as auth_router
from app.api.error_handlers import registration_validation_error
from app.api.health import router as health_router
from app.api.session_auth import router as session_router
from app.api.users import router as users_router
from app.core.auth_cookies import CookiePolicyRejected
from app.core.config import Settings
from app.core.csrf import CsrfConfigurationError, CsrfRejected
from app.core.registration_limits import RegistrationLimits, RegistrationMiddleware
from app.core.session_http import (
    SESSION_PATHS,
    SessionCorsMiddleware,
    SessionHttpLimits,
    SessionHttpMiddleware,
)
from app.core.tokens import TokenConfigurationError
from app.db.session import Database
from app.services.registration import RegistrationUnavailable
from app.services.sessions import (
    AuthenticationDenied,
    PasswordChangeRejected,
    ProfileConflict,
    ProfileUpdateRejected,
    SessionUnavailable,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    limits = RegistrationLimits(settings)
    session_limits = SessionHttpLimits(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(settings)
        application.state.database = database
        try:
            yield
        finally:
            database.dispose()
            limits.clear()
            session_limits.clear()

    expose_docs = settings.environment != "production"
    application = FastAPI(
        title="FinSight API",
        version="0.1.0",
        debug=False,
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    application.state.registration_limits = limits
    application.state.settings = settings
    application.state.session_limits = session_limits
    application.add_exception_handler(RequestValidationError, registration_validation_error)

    @application.exception_handler(RegistrationUnavailable)
    async def registration_unavailable(_request, _error):
        return JSONResponse({"detail": "Registration temporarily unavailable"}, status_code=503)

    async def denied(_request, _error):
        return JSONResponse({"detail": "Authentication denied"}, status_code=401)

    async def rejected(_request, _error):
        return JSONResponse({"detail": "Authentication request rejected"}, status_code=403)

    async def unavailable(_request, _error):
        return JSONResponse({"detail": "Authentication temporarily unavailable"}, status_code=503)

    @application.exception_handler(PasswordChangeRejected)
    async def password_change_rejected(_request, _error):
        return JSONResponse({"detail": "Password change rejected"}, status_code=422)

    @application.exception_handler(ProfileUpdateRejected)
    async def profile_update_rejected(_request, _error):
        return JSONResponse({"detail": "Profile update rejected"}, status_code=422)

    @application.exception_handler(ProfileConflict)
    async def profile_conflict(_request, _error):
        return JSONResponse({"detail": "Profile update unavailable"}, status_code=409)

    @application.exception_handler(Exception)
    async def unexpected_error(request, _error):
        if request.url.path in SESSION_PATHS:
            return JSONResponse(
                {"detail": "Authentication temporarily unavailable"},
                status_code=500,
                headers={"Cache-Control": "no-store"},
            )
        return PlainTextResponse("Internal Server Error", status_code=500)

    application.add_exception_handler(AuthenticationDenied, denied)
    for error in (CsrfRejected, CookiePolicyRejected):
        application.add_exception_handler(error, rejected)
    for error in (SessionUnavailable, TokenConfigurationError, CsrfConfigurationError):
        application.add_exception_handler(error, unavailable)

    application.add_middleware(
        RegistrationMiddleware, limits=limits, body_bytes=settings.registration_body_bytes
    )
    application.add_middleware(
        SessionHttpMiddleware,
        settings=settings,
        limits=session_limits,
    )
    application.add_middleware(SessionCorsMiddleware, settings=settings)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(session_router)
    application.include_router(users_router)
    return application
