from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LLM Gateway Console"
    database_path: str = "./data/llm_gateway.db"
    admin_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_username: str = "admin"
    admin_password: str = ""
    admin_session_secret: str = ""
    admin_session_ttl_seconds: int = 60 * 60 * 12
    provider_request_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    node_managed_zone: str = "gettingstarted.app"
    node_agent_origin: str = "http://127.0.0.1:17890"
    node_enrollment_ttl_seconds: int = Field(default=15 * 60, ge=60, le=86400)
    node_heartbeat_timeout_seconds: int = Field(default=90, ge=60, le=3600)
    node_public_max_ttl_seconds: int = Field(default=24 * 60 * 60, ge=3600, le=604800)
    cloudflare_api_base_url: str = "https://api.cloudflare.com/client/v4"
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_access_service_token_id: str = ""
    cloudflare_access_client_id: str = ""
    cloudflare_access_client_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.admin_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
