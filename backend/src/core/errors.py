"""Standardized error handling for the BIM AI API.

All API errors should use these classes/handlers to ensure consistent
error responses across all endpoints.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger()


class APIError(Exception):
    """Base API error with structured response.

    Args:
        status_code: HTTP status code.
        code: Machine-readable error code (e.g., "INVALID_FILE_TYPE").
        message: Human-readable error message (Vietnamese).
        detail: Optional additional details.
    """

    def __init__(
        self,
        status_code: int = 500,
        code: str = "INTERNAL_ERROR",
        message: str = "Lỗi hệ thống",
        detail: str | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)

    def to_dict(self) -> dict:
        result = {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.detail:
            result["error"]["detail"] = self.detail
        return result


# Common error factories

class NotFoundError(APIError):
    def __init__(self, resource: str = "Tài nguyên", detail: str | None = None):
        super().__init__(404, "NOT_FOUND", f"{resource} không tồn tại", detail)


class ValidationError(APIError):
    def __init__(self, message: str = "Dữ liệu không hợp lệ", detail: str | None = None):
        super().__init__(400, "VALIDATION_ERROR", message, detail)


class AuthenticationError(APIError):
    def __init__(self, message: str = "Chưa xác thực", detail: str | None = None):
        super().__init__(401, "AUTHENTICATION_ERROR", message, detail)


class ForbiddenError(APIError):
    def __init__(self, message: str = "Không có quyền truy cập", detail: str | None = None):
        super().__init__(403, "FORBIDDEN", message, detail)


class RateLimitError(APIError):
    def __init__(self, retry_after: int = 900):
        super().__init__(
            429, "RATE_LIMIT_EXCEEDED",
            f"Quá nhiều yêu cầu. Thử lại sau {retry_after // 60} phút.",
        )


# Exception handlers to register with FastAPI

async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError exceptions."""
    logger.warning("api_error", code=exc.code, message=exc.message, path=str(request.url))
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.error("unhandled_error", error=str(exc), path=str(request.url), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
            }
        },
    )


def register_error_handlers(app):
    """Register all error handlers with a FastAPI app."""
    app.add_exception_handler(APIError, api_error_handler)
    # Don't override HTTPException — let FastAPI handle it
