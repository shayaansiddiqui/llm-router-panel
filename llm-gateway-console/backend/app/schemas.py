from typing import Any

from pydantic import BaseModel, Field


class ProviderIn(BaseModel):
    name: str = Field(min_length=1)
    endpoint_url: str = Field(min_length=1)
    api_key: str | None = None
    is_active: bool = True
    priority: int = Field(default=1, ge=1)
    timeout_seconds: int | None = None


class ProviderOut(ProviderIn):
    id: int
    created_at: str
    updated_at: str


class ModelIn(BaseModel):
    provider_id: int | None = None
    name: str = Field(min_length=1)
    display_name: str | None = None
    is_active: bool = True


class ModelOut(ModelIn):
    id: int
    created_at: str
    updated_at: str


class RoutingRuleIn(BaseModel):
    name: str = Field(min_length=1)
    model_pattern: str = "*"
    provider_id: int | None = None
    priority: int = Field(default=1, ge=1)
    is_active: bool = True


class RoutingRuleOut(RoutingRuleIn):
    id: int
    created_at: str
    updated_at: str


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1)
    provider_ids: list[int] = Field(default_factory=list)
    model_ids: list[int] = Field(default_factory=list)
    is_active: bool = True


class RequestLogOut(BaseModel):
    id: int
    requested_model: str | None
    provider_id: int | None
    provider_name: str | None
    status: str
    status_code: int | None
    error_message: str | None
    duration_ms: int
    created_at: str


class ChatCompletionRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    messages: list[dict[str, Any]] | None = None

    model_config = {"extra": "allow"}
