"""Custom exception handlers for the application."""

from fastapi import Request
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger()


class BIMAgentException(Exception):
    """Base exception for BIM Agent."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class DocumentProcessingError(BIMAgentException):
    """Raised when document processing fails."""

    def __init__(self, message: str = "Lỗi xử lý tài liệu"):
        super().__init__(message, status_code=422)


class GraphQueryError(BIMAgentException):
    """Raised when a knowledge graph query fails."""

    def __init__(self, message: str = "Lỗi truy vấn đồ thị kiến thức"):
        super().__init__(message, status_code=500)


class LLMError(BIMAgentException):
    """Raised when LLM call fails."""

    def __init__(self, message: str = "Lỗi gọi mô hình ngôn ngữ"):
        super().__init__(message, status_code=503)


class RetrievalError(BIMAgentException):
    """Raised when document retrieval fails."""

    def __init__(self, message: str = "Lỗi truy xuất tài liệu"):
        super().__init__(message, status_code=500)


async def bim_agent_exception_handler(
    request: Request, exc: BIMAgentException
) -> JSONResponse:
    """Handle BIMAgentException and return structured error response."""
    logger.error(
        "application_error",
        error_type=type(exc).__name__,
        message=exc.message,
        path=str(request.url),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": type(exc).__name__,
            "message": exc.message,
            "path": str(request.url),
        },
    )
