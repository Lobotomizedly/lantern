"""
Lantern - Narrative Intelligence Platform
FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.routes import (
    subjects,
    search,
    narratives,
    timeline,
    agents,
    artifacts,
    reviews,
    items,
    events,
    dashboard,
)
from app.core.config import settings
from app.core.database import database_pool


class LanternException(Exception):
    """Base exception for Lantern application."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class ResourceNotFoundException(LanternException):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str, resource_id: str | int):
        super().__init__(
            message=f"{resource} with id '{resource_id}' not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"resource": resource, "id": str(resource_id)},
        )


class UnauthorizedException(LanternException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ForbiddenException(LanternException):
    """Raised when user lacks permission for an action."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ConflictException(LanternException):
    """Raised when there's a resource conflict."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Handles startup and shutdown events for database connection pool.
    """
    # Startup: Initialize database connection pool
    await database_pool.connect()

    yield

    # Shutdown: Close database connection pool
    await database_pool.disconnect()


def create_application() -> FastAPI:
    """Factory function to create and configure the FastAPI application."""

    application = FastAPI(
        title="Lantern API",
        description="Narrative Intelligence Platform - API for tracking, analyzing, and understanding narrative dynamics",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count", "X-Page", "X-Page-Size"],
    )

    # Register exception handlers
    register_exception_handlers(application)

    # Include API routers
    register_routers(application)

    return application


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers."""

    @app.exception_handler(LanternException)
    async def lantern_exception_handler(
        request: Request, exc: LanternException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.message,
                    "type": exc.__class__.__name__,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "message": "Validation error",
                    "type": "ValidationError",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "message": "Validation error",
                    "type": "ValidationError",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Log the exception here in production
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "message": "An unexpected error occurred",
                    "type": "InternalServerError",
                    "details": {},
                }
            },
        )


def register_routers(app: FastAPI) -> None:
    """Register all API routers."""

    api_prefix = "/api/v1"

    app.include_router(
        subjects.router,
        prefix=f"{api_prefix}/subjects",
        tags=["Subjects"],
    )
    app.include_router(
        search.router,
        prefix=f"{api_prefix}/search",
        tags=["Search"],
    )
    app.include_router(
        narratives.router,
        prefix=f"{api_prefix}/narratives",
        tags=["Narratives"],
    )
    app.include_router(
        timeline.router,
        prefix=f"{api_prefix}/timeline",
        tags=["Timeline"],
    )
    app.include_router(
        agents.router,
        prefix=f"{api_prefix}/agents",
        tags=["Agents"],
    )
    app.include_router(
        artifacts.router,
        prefix=f"{api_prefix}/artifacts",
        tags=["Artifacts"],
    )
    app.include_router(
        reviews.router,
        prefix=f"{api_prefix}/reviews",
        tags=["Reviews"],
    )
    app.include_router(
        items.router,
        prefix=f"{api_prefix}/items",
        tags=["Items"],
    )
    app.include_router(
        events.router,
        prefix=f"{api_prefix}/events",
        tags=["Events"],
    )
    app.include_router(
        dashboard.router,
        prefix=f"{api_prefix}/dashboard",
        tags=["Dashboard"],
    )

    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check() -> dict:
        return {"status": "healthy", "service": "lantern-api"}


# Create the application instance
app = create_application()
