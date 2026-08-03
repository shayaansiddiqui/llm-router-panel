from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderIn(BaseModel):
    name: str = Field(min_length=1)
    endpoint_url: str = Field(min_length=1)
    api_key: str | None = None
    clear_api_key: bool = False
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


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


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


class EnrollmentTokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_seconds: int = Field(default=900, ge=60, le=86400)


class NodePrepareIn(BaseModel):
    installation_id: str = Field(min_length=16, max_length=128)
    username: str = Field(default="", max_length=255)
    computer_name: str = Field(default="", max_length=255)
    platform: str = Field(min_length=1, max_length=32)
    architecture: str = Field(min_length=1, max_length=32)
    runtime: Literal["ollama"]
    model: str = Field(min_length=1, max_length=256)
    suggested_hostname: str = Field(min_length=1, max_length=253)


class TunnelSelectionIn(BaseModel):
    mode: Literal["create", "existing"]
    id: str | None = Field(default=None, max_length=64)


class AccessSelectionIn(BaseModel):
    mode: Literal["gateway", "api_key", "public"]
    public_ttl_seconds: int = Field(default=0, ge=0, le=86400)


class NodeCommitIn(BaseModel):
    session_id: str = Field(min_length=16, max_length=128)
    tunnel: TunnelSelectionIn
    hostname: str = Field(min_length=1, max_length=253)
    access: AccessSelectionIn
