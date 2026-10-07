"""Application settings using Pydantic Settings.

Security notes:
- All secrets MUST be provided via environment variables or .env file.
- Default values for secrets are deliberately weak/empty to force explicit configuration.
- Startup validation rejects known-weak JWT secrets and missing API keys.
"""

import warnings
from functools import lru_cache
from pydantic_settings import BaseSettings

# Known-weak JWT secrets that must be rejected in production
_WEAK_JWT_SECRETS = {
    "change_this_to_a_random_secret_key_in_production",
    "secret",
    "jwt-secret",
    "test-secret-key-for-testing-only",
    "",
}


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # --- App ---
    app_name: str = "BIM AI Agent"
    app_version: str = "0.2.0"
    debug: bool = False  # Safe default — must opt-in to debug mode

    # --- LLM ---
    gemini_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_fallback_model: str = "gemini-2.5-flash-lite"

    # --- Retrieval ---
    retrieval_top_k: int = 15
    rerank_top_k: int = 5

    # --- Neo4j ---
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""  # Must be set via env

    # --- Qdrant ---
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "qcvn_chunks"

    # --- PostgreSQL ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "bim_agent"
    postgres_password: str = ""  # Must be set via env
    postgres_db: str = "bim_agent_db"

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379

    # --- Auth ---
    jwt_secret_key: str = "change_this_to_a_random_secret_key_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 1440

    # --- Agent ---
    agent_mode: str = "multi_agent"  # multi_agent | langgraph | simple

    # --- Rate limits (per user) ---
    chat_rate_limit_per_minute: int = 20
    chat_rate_limit_per_day: int = 300  # caps Gemini spend: each question makes 3-4 LLM calls
    ifc_rate_limit_per_minute: int = 5  # IFC design / sample generation / upload (CPU-heavy)

    # --- IFC ---
    ifc_upload_dir: str = "data/ifc"
    ifc_max_upload_mb: int = 200

    @property
    def database_url(self) -> str:
        """Build PostgreSQL connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        case_sensitive = False


def _validate_settings(settings: Settings) -> None:
    """Validate critical settings at startup.

    Emits warnings for insecure configurations.
    Raises ValueError in non-debug mode for critical issues.
    """
    issues = []

    # JWT secret validation
    if settings.jwt_secret_key in _WEAK_JWT_SECRETS:
        msg = (
            "JWT_SECRET_KEY is weak or default. "
            "Set a strong random key (≥32 chars) via environment variable."
        )
        if not settings.debug:
            issues.append(msg)
        else:
            warnings.warn(f"⚠️ SECURITY: {msg}", stacklevel=2)

    if len(settings.jwt_secret_key) < 32:
        warnings.warn(
            "⚠️ SECURITY: JWT_SECRET_KEY should be ≥32 characters for production.",
            stacklevel=2,
        )

    # Gemini API key validation
    if not settings.gemini_api_key:
        msg = "GEMINI_API_KEY is empty. LLM features will not work."
        warnings.warn(f"⚠️ CONFIG: {msg}", stacklevel=2)

    # Database password validation
    if not settings.postgres_password:
        msg = "POSTGRES_PASSWORD is empty."
        if not settings.debug:
            issues.append(msg)
        else:
            warnings.warn(f"⚠️ CONFIG: {msg}", stacklevel=2)

    if not settings.neo4j_password:
        msg = "NEO4J_PASSWORD is empty."
        if not settings.debug:
            issues.append(msg)
        else:
            warnings.warn(f"⚠️ CONFIG: {msg}", stacklevel=2)

    if issues and not settings.debug:
        raise ValueError(
            "Critical configuration errors (set DEBUG=true to bypass):\n"
            + "\n".join(f"  - {i}" for i in issues)
        )


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings with validation."""
    settings = Settings()
    _validate_settings(settings)
    return settings
