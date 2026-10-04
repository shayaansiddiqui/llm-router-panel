from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class QualityMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    score: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=1)
    benchmark: str = Field(min_length=1, max_length=256)


class ModelRoutingProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capabilities: list[Literal["text", "vision", "tools", "json_schema"]] = Field(default_factory=list, max_length=4)
    context_tokens: int | None = Field(default=None, ge=1)
    task_quality: dict[str, QualityMeasurement] = Field(default_factory=dict, max_length=32)
    evidence_source: str = Field(min_length=1, max_length=512)
    model_revision: str | None = Field(default=None, min_length=1, max_length=256)


class RoutingEvaluationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    case_id: str = Field(min_length=1, max_length=128)
    model_revision: str = Field(min_length=1, max_length=256)
    rubric: str = Field(min_length=1, max_length=128)
    request_text: str = Field(min_length=1, max_length=8192)
    score: float = Field(ge=0, le=1)
    latency_ms: float | None = Field(default=None, gt=0)
    evaluation_group: str | None = Field(default=None, min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=512)


class RoutingDefaultsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fallback_model_id: int | None = Field(default=None, gt=0)


class RoutingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    task: Literal["general", "coding", "reasoning", "summarization", "translation"] = "general"
    preference: Literal["balanced", "fast", "quality"] = "balanced"
    required_capabilities: list[Literal["text", "vision", "tools", "json_schema"]] = Field(default_factory=list, max_length=4)
    min_context_tokens: int = Field(default=0, ge=0)
    min_quality: float | None = Field(default=None, ge=0, le=1)
