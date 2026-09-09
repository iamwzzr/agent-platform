from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./agent-platform.db"
    llm_provider: Literal["mock", "openai"] = "mock"
    agent_max_revisions: int = Field(default=2, ge=0, le=5)
    provider_retry_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_retry_initial_delay_seconds: float = Field(
        default=0.5,
        ge=0,
        le=60,
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validate_default=True,
    )
    openai_model: str | None = Field(
        default=None,
        validate_default=True,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENT_PLATFORM_",
        extra="ignore",
    )

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_api_key(
        cls,
        value: SecretStr | None,
        info: ValidationInfo,
    ) -> SecretStr | None:
        if info.data.get("llm_provider") == "openai" and (
            value is None or not value.get_secret_value().strip()
        ):
            raise ValueError(
                "AGENT_PLATFORM_OPENAI_API_KEY is required when "
                "AGENT_PLATFORM_LLM_PROVIDER=openai"
            )
        return value

    @field_validator("openai_model")
    @classmethod
    def validate_openai_model(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if info.data.get("llm_provider") == "openai" and (
            value is None or not value.strip()
        ):
            raise ValueError(
                "AGENT_PLATFORM_OPENAI_MODEL is required when "
                "AGENT_PLATFORM_LLM_PROVIDER=openai"
            )
        return value
