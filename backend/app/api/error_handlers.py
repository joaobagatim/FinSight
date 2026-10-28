"""Static validation errors: never echo credentials, input, context or extra keys."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

REGISTRATION_PATH = "/api/v1/auth/register"


async def registration_validation_error(request: Request, error: RequestValidationError):
    # Only this endpoint currently accepts credentials. Preserve other API contracts.
    from fastapi.exception_handlers import request_validation_exception_handler

    if request.url.path != REGISTRATION_PATH:
        return await request_validation_exception_handler(request, error)
    fields = sorted(
        {
            str(item["loc"][1])
            for item in error.errors()
            if len(item.get("loc", ())) == 2
            and item["loc"][0] == "body"
            and item["loc"][1] in {"name", "email", "password"}
        }
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid registration data", "fields": fields},
        headers={"Cache-Control": "no-store"},
    )
