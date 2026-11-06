from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.fde import (
    MANIFEST_SCHEMA_VERSION,
    InputField,
    Manifest,
    Memory,
    OutputSpec,
    create_manifest,
    get_template,
    list_templates,
    manifest_from_qa_app,
    validate_for_publish,
    validate_inputs,
    validate_manifest,
    validate_schema,
)


def _publishable(template_key: str, **overrides) -> Manifest:
    values = {"llm_model_id": "model-1", **overrides}
    if template_key in {"qa", "review", "customer_service"}:
        values.setdefault("knowledge_base_ids", ["kb-1"])
    return create_manifest(template_key, **values)


@pytest.mark.parametrize("template_key", ["qa", "content", "report", "review", "customer_service"])
def test_builtin_templates_create_valid_manifests(template_key: str) -> None:
    template = get_template(template_key)

    assert template is not None
    assert template.name
    assert template.description
    assert template.icon
    manifest = _publishable(template_key)
    assert manifest.schema_version == MANIFEST_SCHEMA_VERSION
    assert manifest.template_key == template_key
    assert manifest.input_fields
    assert manifest.system_prompt
    assert manifest.guardrails.max_output_chars > 0


def test_template_knowledge_rules_and_customer_handoff() -> None:
    templates = {template.key: template for template in list_templates()}

    assert set(templates) == {"qa", "content", "report", "review", "customer_service"}
    assert not templates["content"].knowledge_bases.required
    assert not templates["report"].knowledge_bases.required
    assert all(templates[key].knowledge_bases.required for key in ["qa", "review", "customer_service"])
    assert templates["customer_service"].guardrails.human_handoff
    assert any(tool.name == "human_handoff" for tool in templates["customer_service"].tools)


def test_content_template_supports_general_and_dish_fields() -> None:
    manifest = create_manifest("content")
    fields = {field.key: field for field in manifest.input_fields}

    assert {
        "dish_name",
        "ingredients_taste",
        "selling_points",
        "channel",
        "tone",
        "word_count",
    } <= fields.keys()
    assert fields["channel"].type == "select"
    assert fields["word_count"].type == "number"
    result = validate_inputs(
        manifest,
        {
            "dish_name": "春季新品",
            "ingredients_taste": "清爽、低糖",
            "selling_points": "可持续包装",
            "channel": "官网",
            "tone": "专业",
            "word_count": 600,
        },
    )
    assert result.valid


def test_dynamic_input_types_and_defaults() -> None:
    manifest = create_manifest(
        "content",
        input_fields=[
            InputField(key="title", label="标题", type="text"),
            InputField(key="details", label="详情", type="textarea", required=False),
            InputField(key="count", label="数量", type="number", minimum=1, maximum=5),
            InputField(key="channel", label="渠道", type="select", options=["web", "api"]),
            InputField(key="published", label="已发布", type="boolean", default=False),
        ],
    )

    valid = validate_inputs(manifest, {"title": "标题", "count": 3, "channel": "web"})
    invalid = validate_inputs(
        manifest,
        {"title": "标题", "count": 8, "channel": "unknown", "published": "yes", "extra": 1},
    )

    assert valid.valid
    assert {issue.code for issue in invalid.issues} == {"input_invalid", "unknown_input"}
    assert {issue.path for issue in invalid.issues} >= {"inputs.count", "inputs.channel", "inputs.published"}


def test_missing_required_dynamic_input() -> None:
    result = validate_inputs(create_manifest("report"), {"audience": "管理层"})

    assert not result.publish_ready
    assert any(issue.path == "inputs.topic" and issue.code == "input_required" for issue in result.issues)


def test_content_can_publish_without_knowledge_base() -> None:
    result = validate_for_publish(_publishable("content"), {"model-1"}, set())

    assert result.issues == []
    assert result.publish_ready


def test_report_can_publish_without_knowledge_base() -> None:
    result = validate_for_publish(_publishable("report"), {"model-1"}, set())

    assert result.publish_ready


@pytest.mark.parametrize("template_key", ["qa", "review", "customer_service"])
def test_knowledge_templates_cannot_publish_without_knowledge_base(template_key: str) -> None:
    manifest = _publishable(template_key, knowledge_base_ids=[])

    result = validate_for_publish(manifest, {"model-1"}, set())

    assert not result.publish_ready
    assert any(issue.code == "knowledge_base_required" for issue in result.issues)


def test_unknown_template_is_structured_business_issue() -> None:
    manifest = _publishable("content").model_copy(update={"template_key": "unknown"})

    result = validate_manifest(manifest, {"model-1"}, set())

    assert not result.publish_ready
    assert [(issue.path, issue.code) for issue in result.issues] == [("template_key", "unknown_template")]


def test_invalid_template_default_and_json_schema_are_rejected() -> None:
    with pytest.raises(ValidationError):
        InputField(key="channel", label="渠道", type="select", options=["a"], default="b")
    with pytest.raises(ValidationError):
        OutputSpec(format="markdown", json_schema={"type": "object"})
    with pytest.raises(ValidationError):
        Memory(max_turns=51)


def test_invalid_input_value_returns_structured_issue() -> None:
    manifest = create_manifest("report")

    result = validate_manifest(
        manifest,
        available_model_ids={"model-1"},
        available_knowledge_base_ids=set(),
        input_values={"topic": "主题", "audience": "公众", "word_count": 20},
    )

    assert any(issue.path == "inputs.word_count" and issue.severity == "error" for issue in result.issues)


def test_schema_validation_returns_pydantic_paths() -> None:
    result = validate_schema({"name": "", "template_key": "QA", "system_prompt": ""})

    assert not result.publish_ready
    assert {issue.path for issue in result.issues} >= {"name", "template_key", "system_prompt"}
    assert all(issue.code and issue.message for issue in result.issues)


def test_publish_checks_model_and_every_knowledge_base() -> None:
    manifest = _publishable("qa", llm_model_id="missing-model", knowledge_base_ids=["kb-1", "missing-kb"])

    result = validate_for_publish(manifest, {"model-1"}, {"kb-1"})

    assert not result.publish_ready
    assert {(issue.path, issue.code) for issue in result.issues} == {
        ("llm_model_id", "model_invalid"),
        ("knowledge_base_ids.1", "knowledge_base_invalid"),
    }


def test_publish_requires_model() -> None:
    manifest = create_manifest("content", llm_model_id=None)

    result = validate_for_publish(manifest, {"model-1"}, set())

    assert not result.publish_ready
    assert [issue.code for issue in result.issues] == ["model_required"]


@pytest.mark.parametrize("scenario", ["qa", "content", "report", "review"])
def test_legacy_qa_app_fields_convert_to_compatible_template(scenario: str) -> None:
    app = SimpleNamespace(
        name="旧应用",
        description="旧说明",
        scenario_type=scenario,
        system_prompt="旧提示词",
        llm_model_id="model-old",
        knowledge_bases=[SimpleNamespace(id="kb-old")],
        top_k=6,
        rerank_top_n=2,
        score_threshold=0.4,
    )

    manifest = manifest_from_qa_app(app)

    assert manifest.template_key == scenario
    assert manifest.name == "旧应用"
    assert manifest.llm_model_id == "model-old"
    assert manifest.knowledge_base_ids == ["kb-old"]
    retrieval = next(tool for tool in manifest.tools if tool.name == "knowledge_retrieval")
    assert retrieval.config == {"top_k": 6, "rerank_top_n": 2, "score_threshold": 0.4}


def test_returned_templates_do_not_share_mutable_state() -> None:
    first = get_template("qa")
    second = get_template("qa")

    assert first is not None and second is not None
    first.input_fields[0].label = "已修改"
    assert second.input_fields[0].label == "问题"
