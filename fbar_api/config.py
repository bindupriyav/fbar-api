"""Configuration module using pydantic-settings for environment variable loading."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    DYNAMODB_TABLE_NAME: str = "fbar-filings"
    S3_BUCKET_NAME: str = "irs-cm-fbar-documents-dev"
    RATE_LIMIT_MAX: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    AWS_ENDPOINT_URL: str | None = None
    AWS_REGION: str = "us-east-2"
    AUTH_TOKEN_STORE: str = "tokens.json"

    # Bedrock (FBAR Classification Agent) settings
    BEDROCK_MODEL_ID: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    BEDROCK_MAX_TOKENS: int = 1024
    BEDROCK_TIMEOUT_SECONDS: int = 15

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()

