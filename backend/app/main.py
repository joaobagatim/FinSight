"""Application factory; importing this module does not load local settings."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.error_handlers import registration_validation_error
from app.api.health import router as health_router
from app.core.config import Settings
from app.core.registration_limits import RegistrationLimits, RegistrationMiddleware
from app.db.session import Database
from app.services.registration import RegistrationUnavailable


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    limits = RegistrationLimits(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(settings)
        application.state.database = database
        try:
            yield
        finally:
            database.dispose()
            limits.clear()

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
    application.add_exception_handler(RequestValidationError, registration_validation_error)

    @application.exception_handler(RegistrationUnavailable)
    async def registration_unavailable(_request, _error):
        return JSONResponse({"detail": "Registration temporarily unavailable"}, status_code=503)

    application.add_middleware(
        RegistrationMiddleware, limits=limits, body_bytes=settings.registration_body_bytes
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    return application
