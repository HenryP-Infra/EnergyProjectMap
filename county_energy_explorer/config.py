"""
Application-wide configuration loaded from environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")
    claude_model: str = "claude-sonnet-4-20250514"

    # Database
    database_url: str = Field(
        default="sqlite:///./county_permits.db", env="DATABASE_URL"
    )

    # Langfuse (observability)
    langfuse_public_key: str = Field(default="", env="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", env="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com", env="LANGFUSE_HOST"
    )

    # Google CSE (fallback scraper)
    google_api_key: str = Field(default="", env="GOOGLE_API_KEY")
    google_cse_id: str = Field(default="", env="GOOGLE_CSE_ID")

    # Admin
    admin_password: str = Field(default="changeme", env="ADMIN_PASSWORD")

    # Scraping
    scrape_rate_limit_rps: float = Field(default=2.0, env="SCRAPE_RATE_LIMIT_RPS")
    request_timeout_seconds: int = Field(default=30, env="REQUEST_TIMEOUT_SECONDS")

    # Confidence threshold
    confidence_review_threshold: float = 0.90

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def anthropic_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
