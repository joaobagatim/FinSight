"""Application factory; importing this module does not load local settings."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import PlainTextResponse

from app.api.accounts import router as accounts_router
from app.api.auth import router as auth_router
from app.api.categories import router as categories_router
from app.api.error_handlers import registration_validation_error
from app.api.goals import router as goals_router
from app.api.health import router as health_router
from app.api.session_auth import router as session_router
from app.api.transactions import balance_router
from app.api.transactions import router as transactions_router
from app.api.transfers import router as transfers_router
from app.api.users import router as users_router
from app.core.access_logging import install_access_log_privacy
from app.core.auth_cookies import CookiePolicyRejected
from app.core.config import Settings
from app.core.csrf import CsrfConfigurationError, CsrfRejected
from app.core.registration_limits import RegistrationLimits, RegistrationMiddleware
from app.core.session_http import (
    SessionCorsMiddleware,
    SessionHttpLimits,
    SessionHttpMiddleware,
    is_session_path,
)
from app.core.tokens import TokenConfigurationError
from app.db.session import Database
from app.services.accounts import (
    AccountConflict,
    AccountNotFound,
    AccountOpeningLocked,
    AccountStale,
)
from app.services.categories import CategoryConflict, CategoryNotFound, CategoryStale
from app.services.goals import GoalConflict, GoalNotFound, GoalStale
from app.services.registration import RegistrationUnavailable
from app.services.sessions import (
    AuthenticationDenied,
    PasswordChangeRejected,
    ProfileConflict,
    ProfileUpdateRejected,
    SessionUnavailable,
)
from app.services.transactions import (
    TransactionConflict,
    TransactionNotFound,
    TransactionRejected,
    TransactionRemoved,
    TransactionStale,
)
from app.services.transfers import (
    TransferConflict,
    TransferNotFound,
    TransferRejected,
    TransferRemoved,
    TransferStale,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    install_access_log_privacy()
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

    @application.exception_handler(AccountNotFound)
    async def account_not_found(_request, _error):
        return JSONResponse({"detail": "Account not found"}, status_code=404)

    @application.exception_handler(GoalNotFound)
    async def goal_not_found(_request, _error):
        return JSONResponse({"detail": "Goal not found"}, status_code=404)

    @application.exception_handler(GoalConflict)
    async def goal_conflict(_request, _error):
        return JSONResponse({"detail": "Idempotency key conflict"}, status_code=409)

    @application.exception_handler(GoalStale)
    async def goal_stale(_request, _error):
        return JSONResponse({"detail": "Goal changed; reload before updating"}, status_code=412)

    @application.exception_handler(AccountConflict)
    async def account_conflict(_request, _error):
        return JSONResponse({"detail": "Idempotency key conflict"}, status_code=409)

    @application.exception_handler(AccountOpeningLocked)
    async def account_opening_locked(_request, _error):
        return JSONResponse(
            {"detail": "Account opening is protected by existing history"}, status_code=409
        )

    @application.exception_handler(AccountStale)
    async def account_stale(_request, _error):
        return JSONResponse({"detail": "Account changed; reload before updating"}, status_code=412)

    @application.exception_handler(CategoryNotFound)
    async def category_not_found(_request, _error):
        return JSONResponse({"detail": "Category not found"}, status_code=404)

    @application.exception_handler(CategoryConflict)
    async def category_conflict(_request, _error):
        return JSONResponse(
            {"detail": "Category name already exists for this type"}, status_code=409
        )

    @application.exception_handler(CategoryStale)
    async def category_stale(_request, _error):
        return JSONResponse({"detail": "Category changed; reload before updating"}, status_code=412)

    @application.exception_handler(TransferNotFound)
    async def transfer_not_found(_request, _error):
        return JSONResponse({"detail": "Transfer not found"}, status_code=404)

    @application.exception_handler(TransferRejected)
    async def transfer_rejected(_request, _error):
        return JSONResponse({"detail": "Invalid transfer accounts or date"}, status_code=422)

    @application.exception_handler(TransferConflict)
    async def transfer_conflict(_request, _error):
        return JSONResponse({"detail": "Idempotency key conflict"}, status_code=409)

    @application.exception_handler(TransferStale)
    async def transfer_stale(_request, _error):
        return JSONResponse(
            {"detail": "Transfer changed; reload before proceeding"}, status_code=412
        )

    @application.exception_handler(TransferRemoved)
    async def transfer_removed(_request, _error):
        return JSONResponse({"detail": "Transfer removed"}, status_code=410)

    @application.exception_handler(TransactionNotFound)
    async def transaction_not_found(_request, _error):
        return JSONResponse({"detail": "Transaction not found"}, status_code=404)

    @application.exception_handler(TransactionRejected)
    async def transaction_rejected(_request, _error):
        return JSONResponse({"detail": "Invalid transaction references or date"}, status_code=422)

    @application.exception_handler(TransactionConflict)
    async def transaction_conflict(_request, _error):
        return JSONResponse({"detail": "Idempotency key conflict"}, status_code=409)

    @application.exception_handler(TransactionStale)
    async def transaction_stale(_request, _error):
        return JSONResponse(
            {"detail": "Transaction changed; reload before updating"}, status_code=412
        )

    @application.exception_handler(TransactionRemoved)
    async def transaction_removed(_request, _error):
        return JSONResponse({"detail": "Transaction removed"}, status_code=410)

    @application.exception_handler(Exception)
    async def unexpected_error(request, _error):
        if is_session_path(request.url.path):
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
    application.include_router(accounts_router)
    application.include_router(categories_router)
    application.include_router(goals_router)
    application.include_router(transactions_router)
    application.include_router(transfers_router)
    application.include_router(balance_router)
    return application
