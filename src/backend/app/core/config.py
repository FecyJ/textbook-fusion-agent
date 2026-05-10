from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_api_key: str | None = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"))
    llm_api_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_BASE_URL", "DEEPSEEK_API_BASE_URL"),
    )
    llm_model: str = Field(default="", validation_alias=AliasChoices("LLM_MODEL", "DEEPSEEK_MODEL"))
    llm_provider: str = Field(default="openai-compatible", validation_alias=AliasChoices("LLM_PROVIDER", "DEEPSEEK_PROVIDER"))

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
