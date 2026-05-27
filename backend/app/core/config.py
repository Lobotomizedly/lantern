"""
Application configuration using pydantic-settings.

This module defines all environment variables and configuration settings
for the Lantern Narrative Intelligence Platform.
"""

import secrets
from functools import lru_cache
from typing import Optional

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables or a .env file.
    Secret values are wrapped in SecretStr for security.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================================
    # Application Settings
    # ==========================================================================

    app_name: str = Field(
        default="Lantern",
        description="Application name",
    )
    app_version: str = Field(
        default="0.1.0",
        description="Application version",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment (development, staging, production)",
    )

    # ==========================================================================
    # Database Settings
    # ==========================================================================

    database_url: str = Field(
        default="postgresql+asyncpg://lantern:lantern@localhost:5432/lantern",
        description="PostgreSQL connection URL with asyncpg driver",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+asyncpg:// for async SQLAlchemy."""
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    database_pool_size: int = Field(
        default=10,
        description="Database connection pool size",
    )
    database_max_overflow: int = Field(
        default=20,
        description="Maximum overflow connections beyond pool_size",
    )
    database_pool_timeout: int = Field(
        default=30,
        description="Connection pool timeout in seconds",
    )
    database_echo: bool = Field(
        default=False,
        description="Echo SQL statements (for debugging)",
    )

    # ==========================================================================
    # Redis Settings
    # ==========================================================================

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching and Celery broker",
    )
    redis_cache_ttl: int = Field(
        default=3600,
        description="Default cache TTL in seconds",
    )

    # ==========================================================================
    # AWS / S3 Settings
    # ==========================================================================

    aws_access_key_id: Optional[SecretStr] = Field(
        default=None,
        description="AWS access key ID",
    )
    aws_secret_access_key: Optional[SecretStr] = Field(
        default=None,
        description="AWS secret access key",
    )
    aws_region: str = Field(
        default="us-east-1",
        description="AWS region",
    )
    s3_bucket: str = Field(
        default="lantern-artifacts",
        description="S3 bucket for artifact storage",
    )
    s3_endpoint_url: Optional[str] = Field(
        default=None,
        description="Custom S3 endpoint URL (for MinIO, LocalStack, etc.)",
    )

    # ==========================================================================
    # AI Provider Settings
    # ==========================================================================

    anthropic_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Anthropic API key for Claude models",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Default Anthropic model to use",
    )

    openai_api_key: Optional[SecretStr] = Field(
        default=None,
        description="OpenAI API key",
    )
    openai_model: str = Field(
        default="gpt-4-turbo-preview",
        description="Default OpenAI model to use",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="Embedding vector dimensions",
    )

    # ==========================================================================
    # Temporal Workflow Settings
    # ==========================================================================

    temporal_host: str = Field(
        default="localhost:7233",
        description="Temporal server host and port",
    )
    temporal_namespace: str = Field(
        default="lantern",
        description="Temporal namespace",
    )
    temporal_task_queue: str = Field(
        default="lantern-tasks",
        description="Default Temporal task queue",
    )

    # ==========================================================================
    # Celery Settings
    # ==========================================================================

    celery_broker_url: Optional[str] = Field(
        default=None,
        description="Celery broker URL (defaults to redis_url if not set)",
    )
    celery_result_backend: Optional[str] = Field(
        default=None,
        description="Celery result backend URL (defaults to redis_url if not set)",
    )

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def set_celery_broker(cls, v: Optional[str], info) -> str:
        """Default Celery broker to Redis URL if not specified."""
        if v is None:
            return info.data.get("redis_url", "redis://localhost:6379/0")
        return v

    @field_validator("celery_result_backend", mode="before")
    @classmethod
    def set_celery_backend(cls, v: Optional[str], info) -> str:
        """Default Celery result backend to Redis URL if not specified."""
        if v is None:
            return info.data.get("redis_url", "redis://localhost:6379/0")
        return v

    # ==========================================================================
    # Observability Settings
    # ==========================================================================

    langfuse_public_key: Optional[SecretStr] = Field(
        default=None,
        description="Langfuse public key for LLM observability",
    )
    langfuse_secret_key: Optional[SecretStr] = Field(
        default=None,
        description="Langfuse secret key",
    )
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        description="Langfuse host URL",
    )

    # ==========================================================================
    # Authentication Settings
    # ==========================================================================

    jwt_secret_key: Optional[SecretStr] = Field(
        default=None,
        description="Secret key for JWT token signing. REQUIRED in production.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration time in minutes",
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration time in days",
    )

    @model_validator(mode="after")
    def validate_jwt_secret_key(self) -> "Settings":
        """
        Validate JWT secret key configuration.

        In production: Requires JWT_SECRET_KEY to be explicitly set via environment.
        In non-production: Generates a random secret if not provided (with warning).
        """
        # Define known insecure default values that should be rejected
        insecure_defaults = {
            "CHANGE-THIS-IN-PRODUCTION-USE-SECURE-SECRET",
            "secret",
            "changeme",
            "your-secret-key",
            "jwt-secret",
        }

        is_production = self.environment.lower() == "production"

        if self.jwt_secret_key is None:
            if is_production:
                raise ValueError(
                    "CRITICAL: JWT_SECRET_KEY environment variable is required in production. "
                    "Generate a secure secret with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            # Generate a random secret for development/staging
            import warnings
            warnings.warn(
                "JWT_SECRET_KEY not set. Generating a random secret for non-production use. "
                "This secret will change on each restart, invalidating existing tokens.",
                UserWarning,
                stacklevel=2,
            )
            self.jwt_secret_key = SecretStr(secrets.token_urlsafe(64))
        else:
            # Check if the provided secret is an insecure default
            secret_value = self.jwt_secret_key.get_secret_value()
            if secret_value.lower() in {s.lower() for s in insecure_defaults}:
                if is_production:
                    raise ValueError(
                        f"CRITICAL: JWT_SECRET_KEY contains an insecure default value. "
                        "Generate a secure secret with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                    )
                import warnings
                warnings.warn(
                    "JWT_SECRET_KEY contains an insecure default value. "
                    "This is acceptable for development but MUST be changed for production.",
                    UserWarning,
                    stacklevel=2,
                )

            # Validate minimum secret length (at least 32 characters for HS256)
            if len(secret_value) < 32:
                if is_production:
                    raise ValueError(
                        "CRITICAL: JWT_SECRET_KEY must be at least 32 characters long. "
                        "Generate a secure secret with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                    )
                import warnings
                warnings.warn(
                    f"JWT_SECRET_KEY is only {len(secret_value)} characters. "
                    "Recommended minimum is 32 characters for security.",
                    UserWarning,
                    stacklevel=2,
                )

        return self

    # ==========================================================================
    # Content Processing Settings
    # ==========================================================================

    max_content_length: int = Field(
        default=100000,
        description="Maximum content length to process (characters)",
    )
    whisper_model: str = Field(
        default="base",
        description="Whisper model size (tiny, base, small, medium, large)",
    )

    # ==========================================================================
    # Rate Limiting Settings
    # ==========================================================================

    rate_limit_requests_per_minute: int = Field(
        default=60,
        description="API rate limit: requests per minute",
    )
    rate_limit_burst: int = Field(
        default=10,
        description="API rate limit: burst allowance",
    )

    # ==========================================================================
    # CORS Settings
    # ==========================================================================

    cors_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8000",
            "https://frontend-production-6440.up.railway.app",
        ],
        description="Allowed CORS origins",
    )

    # ==========================================================================
    # Helper Properties
    # ==========================================================================

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() == "development"

    @property
    def sync_database_url(self) -> str:
        """Get synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "")

    @property
    def CORS_ORIGINS(self) -> list[str]:
        """Get CORS origins (uppercase property for consistency)."""
        return self.cors_origins


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once and reused
    throughout the application lifecycle.

    Returns:
        Settings: Application settings instance.
    """
    return Settings()


# Global settings instance
settings = get_settings()
