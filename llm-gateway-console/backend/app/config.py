from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LLM Gateway Console"
    database_path: str = "./data/llm_gateway.db"
    admin_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_session_secret: str = "change-this-admin-session-secret"
    admin_session_ttl_seconds: int = 60 * 60 * 12
    provider_request_timeout_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.admin_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
