from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MANIFEST_SCHEMA_VERSION = "fde.app/v2"


class FDEModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InputField(FDEModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "textarea", "number", "select", "boolean"] = "text"
    description: str = Field(default="", max_length=500)
    required: bool = True
    placeholder: str = Field(default="", max_length=300)
    options: list[str] = Field(default_factory=list, max_length=50)
    default: str | float | bool | None = None
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_configuration(self) -> "InputField":
        if self.type == "select" and not self.options:
            raise ValueError("select fields require at least one option")
        if self.type != "select" and self.options:
            raise ValueError("options are only supported by select fields")
        if len(set(self.options)) != len(self.options):
            raise ValueError("options cannot contain duplicates")
        if any(not option.strip() or len(option) > 120 for option in self.options):
            raise ValueError("options must contain between 1 and 120 characters")
        if self.type != "number" and (self.minimum is not None or self.maximum is not None):
            raise ValueError("minimum and maximum are only supported by number fields")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.default is not None:
            validate_input_value(self, self.default, path="default")
        return self


class OutputSpec(FDEModel):
    format: Literal["markdown", "text", "json"] = "markdown"
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_json_schema(self) -> "OutputSpec":
        if self.json_schema is not None and self.format != "json":
            raise ValueError("json_schema requires json output format")
        return self


class Tool(FDEModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    tool_id: str | None = Field(default=None, max_length=180)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ModelSettings(FDEModel):
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=64, le=32768)
    thinking_mode: Literal["auto", "enabled", "disabled"] = "auto"


class AgentSettings(FDEModel):
    max_steps: int = Field(default=8, ge=1, le=20)
    require_confirmation_for_side_effects: bool = True
    show_tool_steps: bool = True
    long_term_memory: bool = False
    # tool: 知识库作为工具，由 Agent 决定何时检索；always: 每轮先检索再交给 Agent
    knowledge_mode: Literal["tool", "always"] = "tool"


class Guardrails(FDEModel):
    blocked_topics: list[str] = Field(default_factory=list, max_length=30)
    require_citations: bool = False
    refuse_without_evidence: bool = False
    human_handoff: bool = False
    max_output_chars: int = Field(default=8000, ge=100, le=50000)

    @model_validator(mode="after")
    def validate_blocked_topics(self) -> "Guardrails":
        if any(not topic or len(topic) > 120 for topic in self.blocked_topics):
            raise ValueError("blocked topics must contain between 1 and 120 characters")
        return self


class Memory(FDEModel):
    enabled: bool = True
    max_turns: int = Field(default=10, ge=1, le=50)


class Delivery(FDEModel):
    channel: Literal["web", "api", "both"] = "web"
    show_citations: bool = False
    allow_copy: bool = True
    allow_export: bool = False


class Experience(FDEModel):
    opening: str = Field(default="", max_length=1000)
    suggestions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_suggestions(self) -> "Experience":
        if any(not item or len(item) > 120 for item in self.suggestions):
            raise ValueError("suggestions must contain between 1 and 120 characters")
        return self


class Manifest(FDEModel):
    schema_version: Literal["fde.app/v1", "fde.app/v2"] = MANIFEST_SCHEMA_VERSION
    type: Literal["simple", "agent"] = "simple"
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    template_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    system_prompt: str = Field(min_length=1, max_length=12000)
    llm_model_id: str | None = Field(default=None, max_length=180)
    model: ModelSettings = Field(default_factory=ModelSettings)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=20)
    input_fields: list[InputField] = Field(default_factory=list, max_length=30)
    output: OutputSpec = Field(default_factory=OutputSpec)
    tools: list[Tool] = Field(default_factory=list, max_length=10)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    memory: Memory = Field(default_factory=Memory)
    delivery: Delivery = Field(default_factory=Delivery)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    experience: Experience = Field(default_factory=Experience)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> "Manifest":
        if len(set(self.knowledge_base_ids)) != len(self.knowledge_base_ids):
            raise ValueError("knowledge_base_ids cannot contain duplicates")
        if any(not knowledge_base_id or len(knowledge_base_id) > 180 for knowledge_base_id in self.knowledge_base_ids):
            raise ValueError("knowledge base IDs must contain between 1 and 180 characters")
        field_keys = [field.key for field in self.input_fields]
        if len(set(field_keys)) != len(field_keys):
            raise ValueError("input field keys cannot contain duplicates")
        tool_names = [tool.name for tool in self.tools]
        if len(set(tool_names)) != len(tool_names):
            raise ValueError("tool names cannot contain duplicates")
        if self.type == "simple" and any(tool.tool_id for tool in self.tools):
            raise ValueError("external tools require an agent application")
        return self


def validate_input_value(field: InputField, value: Any, path: str = "value") -> None:
    if value is None or value == "":
        if field.required:
            raise ValueError(f"{path} is required")
        return
    if field.type == "boolean":
        if type(value) is not bool:
            raise ValueError(f"{path} must be a boolean")
        return
    if field.type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{path} must be a number")
        if field.minimum is not None and value < field.minimum:
            raise ValueError(f"{path} must be at least {field.minimum}")
        if field.maximum is not None and value > field.maximum:
            raise ValueError(f"{path} must be at most {field.maximum}")
        return
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    if field.type == "select" and value not in field.options:
        raise ValueError(f"{path} must be one of the configured options")
    if field.type == "text" and len(value) > 1000:
        raise ValueError(f"{path} cannot exceed 1000 characters")
    if field.type == "textarea" and len(value) > 20000:
        raise ValueError(f"{path} cannot exceed 20000 characters")


def manifest_fingerprint(manifest: "Manifest | dict[str, Any]") -> str:
    """Stable hash of an app configuration, used to tie evaluation runs to the exact draft they tested."""
    data = manifest.model_dump(mode="json") if isinstance(manifest, BaseModel) else manifest
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
