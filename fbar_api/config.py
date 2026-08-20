"""Configuration module using pydantic-settings for environment variable loading."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DYNAMODB_TABLE_NAME: str = "fbar-filings"
    S3_BUCKET_NAME: str = "irs-cm-fbar-documents-dev"
    RATE_LIMIT_MAX: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    AWS_ENDPOINT_URL: str | None = None
    AUTH_TOKEN_STORE: str = "tokens.json"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
