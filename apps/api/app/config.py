from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./autonomous_company.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_mode: str = "direct"
    llm_mode: str = "mock"
    openai_api_key: str | None = None
    trusted_receipt_hmac_secret: str | None = None
    real_money_enabled: bool = False
    bug_bounty_external_actions_enabled: bool = False
    # No built-in credential: every owner control fails closed until the
    # operator explicitly configures OWNER_TOKEN.
    owner_token: str | None = None
    paper_treasury_cents: int = Field(default=1_000_000, ge=0)

    @field_validator("queue_mode")
    @classmethod
    def validate_queue_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"direct", "redis"}:
            raise ValueError("QUEUE_MODE must be direct or redis")
        return value

    @field_validator("llm_mode")
    @classmethod
    def validate_llm_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"mock", "openai"}:
            raise ValueError("LLM_MODE must be mock or openai")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
