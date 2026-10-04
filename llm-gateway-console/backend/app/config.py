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
    provider_request_timeout_seconds: int = 180
    router_encoder_path: str = ""
    router_encoder_revision: str = ""
    router_evaluation_rubric: str = ""
    router_encoder_threads: int = 2
    router_min_similarity: float = 0.5
    router_probe_timeout_seconds: float = 3.0
    router_uncertain_policy: str = "reject"
    router_auto_prepare: bool = True
    router_selection_mode: str = "local_llm"
    router_selector_url: str = "http://127.0.0.1:11434"
    router_selector_model: str = "qwen3.5:2b"
    router_selector_timeout_seconds: float = 15.0
    ollama_chat_context_tokens: int = 16384

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.admin_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_router_settings() -> Settings:
    """Operator preparation is persisted, so all workers see the same revision."""
    import json
    from .database import fetch_one
    row = fetch_one("SELECT settings_json FROM routing_configuration WHERE id = 1")
    if not row:
        return get_settings()
    values = json.loads(row["settings_json"])
    allowed = {"router_encoder_path", "router_encoder_revision", "router_evaluation_rubric",
               "router_uncertain_policy"}
    return get_settings().model_copy(update={key: value for key, value in values.items() if key in allowed})
